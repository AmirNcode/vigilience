"""End-to-end tests for pin-gate/pin_gate.py against a fake upstream.

Run via tests/pin-gate-test.sh (stdlib only, no Docker needed).
"""

import asyncio
import base64
import os
import re
import secrets
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pin-gate"))
import pin_gate  # noqa: E402

PIN = "482915"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def fake_upstream(reader, writer):
    """Echo the request head; speak a trivial websocket echo after a 101."""
    head = await reader.readuntil(b"\r\n\r\n")
    if b"Upgrade: websocket" in head:
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        while data := await reader.read(1024):
            writer.write(b"echo:" + data)
            await writer.drain()
    else:
        body = b"UPSTREAM\n" + head
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
        # Answer a pipelined second request too, to prove the gate drops it.
        try:
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 0.3)
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nLEAKED")
        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
            pass
    await writer.drain()
    writer.close()


class GateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.up_port, self.port = free_port(), free_port()
        self.upstream = await asyncio.start_server(fake_upstream, "127.0.0.1", self.up_port)
        key = secrets.token_urlsafe(32).encode()
        self.gate = pin_gate.Gate(pin_gate.hash_pin(PIN, iterations=1000), key, "127.0.0.1", self.up_port, 86400)
        self.server = await asyncio.start_server(self.gate.handle, "127.0.0.1", self.port, limit=pin_gate.MAX_HEAD)

    async def asyncTearDown(self):
        self.server.close()
        self.upstream.close()

    async def raw(self, data, read_after=None):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(data)
        await writer.drain()
        if read_after:
            await asyncio.sleep(0.2)
            writer.write(read_after)
            await writer.drain()
        out = b""
        # Read until the gate closes, or until it goes quiet (open websocket).
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(65536), 2.5)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            out += chunk
        writer.close()
        return out

    async def get(self, path, headers=""):
        return await self.raw(("GET %s HTTP/1.1\r\nHost: x\r\nAccept: text/html\r\n%s\r\n" % (path, headers)).encode())

    async def post_pin(self, pin, nxt="/lovelace/0"):
        body = ("pin=%s&next=%s" % (pin, nxt)).encode()
        return await self.raw(b"POST /__vig_pin HTTP/1.1\r\nHost: x\r\nContent-Type: application/x-www-form-urlencoded\r\n"
                              b"Content-Length: %d\r\n\r\n%s" % (len(body), body))

    async def unlock(self):
        out = await self.post_pin(PIN)
        return re.search(rb"Set-Cookie: (vig_pin=[^;]+)", out).group(1).decode()

    async def test_ui_and_login_need_pin(self):
        for path in ("/", "/lovelace/0", "/auth/authorize?x=1", "/auth/login_flow", "/frontend_latest/app.js"):
            out = await self.get(path)
            self.assertIn(b" 401 ", out.split(b"\r\n")[0], path)
            self.assertNotIn(b"UPSTREAM", out, path)
        self.assertIn(b'name="pin"', await self.get("/"))

    async def test_correct_pin_sets_24h_cookie_and_unlocks(self):
        out = await self.post_pin(PIN)
        self.assertIn(b" 303 ", out.split(b"\r\n")[0])
        self.assertIn(b"Location: /lovelace/0", out)
        self.assertIn(b"Max-Age=86400; HttpOnly; SameSite=Lax", out)
        cookie = await self.unlock()
        out = await self.get("/lovelace/0", "Cookie: other=1; %s\r\n" % cookie)
        self.assertIn(b"UPSTREAM", out)
        self.assertIn(b"Cookie: other=1", out)
        self.assertNotIn(b"vig_pin", out.split(b"UPSTREAM", 1)[1])

    async def test_wrong_pin_and_lockout(self):
        for _ in range(pin_gate.CLIENT_MAX_FAILS):
            out = await self.post_pin("000000")
            self.assertIn(b"Wrong PIN", out)
        out = await self.post_pin(PIN)
        self.assertIn(b" 429 ", out.split(b"\r\n")[0])
        self.assertNotIn(b"Set-Cookie", out)

    async def test_parallel_guesses_hit_lockout(self):
        outs = await asyncio.gather(*(self.post_pin("%06d" % i) for i in range(20)))
        wrong = sum(b"Wrong PIN" in o for o in outs)
        self.assertLessEqual(wrong, pin_gate.CLIENT_MAX_FAILS)
        self.assertGreaterEqual(sum(b" 429 " in o for o in outs), 20 - pin_gate.CLIENT_MAX_FAILS)

    async def test_short_or_non_numeric_pin_rejected(self):
        for pin in ("12345", "abcdef"):
            self.assertIn(b"Wrong PIN", await self.post_pin(pin))

    async def test_open_redirect_blocked(self):
        out = await self.post_pin(PIN, nxt="//evil.example")
        self.assertIn(b"Location: /\r\n", out)

    async def test_expired_or_forged_cookie_rejected(self):
        old = pin_gate.make_cookie(self.gate.key, 10, now=time.time() - 100)
        forged = "9999999999." + base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
        for c in (old, forged, "garbage"):
            self.assertNotIn(b"UPSTREAM", await self.get("/", "Cookie: vig_pin=%s\r\n" % c))

    async def test_token_paths_pass_without_pin(self):
        for path in ("/api/states", "/api/webhook/abc", "/auth/token"):
            self.assertIn(b"UPSTREAM", await self.get(path), path)

    async def test_traversal_into_gated_routes_rejected(self):
        for path in ("/api/../auth/authorize", "/api/%2e%2e/auth/login_flow", "/api/..%2Fauth", "/api//x", "/api/.\\x"):
            out = await self.get(path)
            self.assertIn(b" 400 ", out.split(b"\r\n")[0], path)

    async def test_no_request_smuggling_after_exempt_request(self):
        out = await self.raw(b"GET /api/states HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n",
                             read_after=b"GET /lovelace HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertIn(b"Connection: close", out)
        self.assertNotIn(b"LEAKED", out)

    async def test_client_forwarded_headers_replaced(self):
        out = await self.get("/api/x", "X-Forwarded-For: 1.2.3.4\r\nForwarded: for=1.2.3.4\r\n")
        self.assertIn(b"X-Forwarded-For: 127.0.0.1", out)
        self.assertNotIn(b"1.2.3.4", out)

    async def test_websocket_api_passes_and_other_upgrades_do_not(self):
        ws = ("GET %s HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
              "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
        out = await self.raw((ws % "/api/websocket").encode(), read_after=b"hello")
        self.assertIn(b"101 Switching", out)
        self.assertIn(b"echo:hello", out)
        out = await self.raw((ws % "/api/states").encode(), read_after=b"hello")
        self.assertNotIn(b"101 Switching", out)
        self.assertNotIn(b"echo:", out)

    async def test_service_worker_blocked(self):
        self.assertIn(b" 404 ", (await self.get("/sw-modern.js")).split(b"\r\n")[0])

    async def test_lock_clears_cookie(self):
        self.assertIn(b"vig_pin=; Path=/; Max-Age=0", await self.get("/__vig_pin/lock"))

    async def test_non_html_requests_get_plain_401(self):
        out = await self.raw(b"POST /auth/login_flow HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n")
        self.assertIn(b"PIN required", out)


class HashTest(unittest.TestCase):
    def test_hash_roundtrip_and_no_dollar(self):
        h = pin_gate.hash_pin(PIN, iterations=1000)
        self.assertNotIn("$", h)
        self.assertTrue(pin_gate.check_pin(PIN, h))
        self.assertFalse(pin_gate.check_pin("482916", h))
        self.assertFalse(pin_gate.check_pin(PIN, "nonsense"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
