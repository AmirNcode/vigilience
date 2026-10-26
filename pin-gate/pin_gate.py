"""Vigilience PIN gate: a small reverse proxy in front of Home Assistant.

Listens on :8123 (LAN) and forwards to Home Assistant on loopback. Browser
traffic must present a PIN cookie (valid 24 h) before anything reaches Home
Assistant, including its login page. Requests that Home Assistant itself
authenticates with a token (REST API, websocket, token refresh, webhooks)
pass through, so the Companion app keeps working in the background.

Standard library only. The proxy parses the request head, decides, then pipes
raw bytes in both directions with one upstream connection per request
(`Connection: close`), so websockets and streaming responses need no special
handling.

    python3 pin_gate.py            run the gate (configured via environment)
    python3 pin_gate.py hash       read a PIN on stdin, print its hash line
"""

import asyncio
import base64
import hashlib
import hmac
import html
import logging
import os
import re
import secrets
import sys
import time
from urllib.parse import parse_qs, unquote, urlsplit

COOKIE = "vig_pin"
PIN_PATH = "/__vig_pin"
LOCK_PATH = "/__vig_pin/lock"
PIN_RE = re.compile(r"^[0-9]{6,32}$")
PBKDF2_ITERATIONS = 600_000
MAX_HEAD = 64 * 1024

# Paths Home Assistant authenticates itself (token required) and the
# Companion app calls natively without the webview's cookies.
TOKEN_PATH_PREFIXES = ("/api/",)
TOKEN_PATHS = ("/auth/token", "/auth/revoke")
# Service workers can serve a cached UI without touching the network; 404
# makes browsers unregister them so every page load goes through the gate.
BLOCKED_PATHS = ("/sw-modern.js", "/sw-legacy.js", "/service_worker.js")

# Brute-force limits: per client, plus a global ceiling across all clients.
CLIENT_MAX_FAILS, CLIENT_WINDOW = 5, 15 * 60
GLOBAL_MAX_FAILS, GLOBAL_WINDOW = 30, 60 * 60

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-connection", "te", "trailer", "upgrade",
    "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "forwarded",
}

log = logging.getLogger("pin-gate")


# ── PIN hashing ──────────────────────────────────────────────────────────
# Format: pbkdf2:<iterations>:<salt b64>:<hash b64>. No "$", so Docker Compose
# env interpolation leaves it alone.

def hash_pin(pin, iterations=PBKDF2_ITERATIONS):
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, iterations)
    return "pbkdf2:%d:%s:%s" % (iterations, b64(salt), b64(dk))


def check_pin(pin, stored):
    try:
        scheme, iterations, salt, expected = stored.split(":")
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pin.encode(), unb64(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, unb64(expected))


def b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# ── Session cookie: "<expiry>.<hmac>" ────────────────────────────────────

def make_cookie(key, ttl, now=None):
    expiry = str(int((now or time.time()) + ttl))
    return expiry + "." + b64(hmac.new(key, expiry.encode(), hashlib.sha256).digest())


def cookie_valid(key, value, now=None):
    expiry, _, sig = value.partition(".")
    if not expiry.isdigit() or not sig:
        return False
    good = b64(hmac.new(key, expiry.encode(), hashlib.sha256).digest())
    return hmac.compare_digest(sig, good) and int(expiry) > (now or time.time())


class RateLimiter:
    def __init__(self):
        self.fails = {}
        self.global_fails = []

    def _prune(self, now):
        self.global_fails = [t for t in self.global_fails if now - t < GLOBAL_WINDOW]
        for ip in list(self.fails):
            self.fails[ip] = [t for t in self.fails[ip] if now - t < CLIENT_WINDOW]
            if not self.fails[ip]:
                del self.fails[ip]

    def locked_for(self, ip, now=None):
        """Seconds until this client may try again (0 = allowed)."""
        now = now or time.time()
        self._prune(now)
        waits = [0]
        mine = self.fails.get(ip, [])
        if len(mine) >= CLIENT_MAX_FAILS:
            waits.append(mine[0] + CLIENT_WINDOW - now)
        if len(self.global_fails) >= GLOBAL_MAX_FAILS:
            waits.append(self.global_fails[0] + GLOBAL_WINDOW - now)
        return int(max(waits)) + (1 if max(waits) > 0 else 0)

    def fail(self, ip, now=None):
        now = now or time.time()
        self.fails.setdefault(ip, []).append(now)
        self.global_fails.append(now)

    def success(self, ip):
        mine = self.fails.pop(ip, [])
        if mine and mine[-1] in self.global_fails:
            self.global_fails.remove(mine[-1])


# ── HTTP plumbing ────────────────────────────────────────────────────────

class Request:
    def __init__(self, head):
        lines = head.decode("latin-1").split("\r\n")
        self.method, self.target, self.version = lines[0].split(" ", 2)
        if not self.version.startswith("HTTP/1."):
            raise ValueError("unsupported version")
        self.headers = []
        for line in lines[1:]:
            if not line:
                continue
            name, sep, value = line.partition(":")
            if not sep or not name or name != name.strip():
                raise ValueError("bad header")
            self.headers.append((name, value.strip()))
        self.path = urlsplit(self.target).path or "/"

    def header(self, name):
        name = name.lower()
        for k, v in self.headers:
            if k.lower() == name:
                return v
        return None

    def cookies(self):
        jar = {}
        for k, v in self.headers:
            if k.lower() == "cookie":
                for part in v.split(";"):
                    ck, _, cv = part.strip().partition("=")
                    jar.setdefault(ck, cv)
        return jar


def safe_path(path):
    """Reject paths that could be normalised into a different route upstream."""
    if not path.startswith("/") or "\\" in path or "//" in path:
        return False
    decoded = unquote(path)
    return not any(s in (".", "..") for s in decoded.split("/")) and "\x00" not in decoded


def is_websocket_handshake(req):
    return (
        req.method == "GET"
        and (req.header("upgrade") or "").lower() == "websocket"
        and req.header("sec-websocket-key")
        and req.header("sec-websocket-version") == "13"
        and req.header("content-length") is None
        and req.header("transfer-encoding") is None
    )


def response(status, body=b"", headers=()):
    reason = {200: "OK", 303: "See Other", 400: "Bad Request", 401: "Unauthorized",
              404: "Not Found", 413: "Payload Too Large", 429: "Too Many Requests",
              502: "Bad Gateway"}[status]
    lines = ["HTTP/1.1 %d %s" % (status, reason), "Content-Length: %d" % len(body),
             "Connection: close", "Cache-Control: no-store"]
    lines += ["%s: %s" % h for h in headers]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


PAGE_HEADERS = (
    ("Content-Type", "text/html; charset=utf-8"),
    ("X-Frame-Options", "DENY"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"),
)


def pin_page(next_path, message=""):
    msg = '<p class="msg">%s</p>' % html.escape(message) if message else ""
    return ("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Vigilience · PIN</title>
<style>
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1419;
       color:#e6e9ed;font:16px/1.4 system-ui,-apple-system,sans-serif}
  form{width:min(320px,calc(100vw - 32px));display:grid;gap:14px;text-align:center}
  h1{font-size:20px;font-weight:600;margin:0 0 4px}
  input{font-size:28px;letter-spacing:.3em;text-align:center;padding:12px;border-radius:10px;
        border:1px solid #2c3540;background:#161d24;color:inherit}
  input:focus{outline:2px solid #4fa3ff;border-color:transparent}
  button{font-size:16px;padding:12px;border:0;border-radius:10px;background:#2f7de1;color:#fff}
  .msg{margin:0;color:#ff8a80}
  .hint{margin:0;color:#8a96a3;font-size:13px}
</style></head><body>
<form method="post" action="%s">
  <h1>Vigilience</h1>
  <input name="pin" type="password" inputmode="numeric" pattern="[0-9]*" minlength="6"
         maxlength="32" autocomplete="current-password" autofocus required aria-label="PIN">
  <input type="hidden" name="next" value="%s">
  %s
  <button type="submit">Unlock</button>
  <p class="hint">Stays unlocked on this device for 24 hours.</p>
</form></body></html>""" % (PIN_PATH, html.escape(next_path, quote=True), msg)).encode()


def safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if value.startswith(PIN_PATH):
        return "/"
    return value


class Gate:
    def __init__(self, pin_hash, key, upstream_host, upstream_port, ttl):
        self.pin_hash = pin_hash
        self.key = key
        self.upstream = (upstream_host, upstream_port)
        self.ttl = ttl
        self.limiter = RateLimiter()

    async def handle(self, reader, writer):
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "unknown"
        if ip.startswith("::ffff:"):
            ip = ip[7:]
        try:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            except asyncio.LimitOverrunError:
                writer.write(response(413))
                return
            except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
                return
            try:
                req = Request(head[:-4])
            except ValueError:
                writer.write(response(400))
                return
            await self.route(req, head, reader, writer, ip)
        except ConnectionError:
            pass
        except Exception:
            log.exception("request failed")
        finally:
            try:
                await writer.drain()
            except ConnectionError:
                pass
            writer.close()

    async def route(self, req, head, reader, writer, ip):
        path = req.path
        if not safe_path(path):
            writer.write(response(400))
            return
        if path in BLOCKED_PATHS:
            writer.write(response(404))
            return
        if path == LOCK_PATH:
            writer.write(response(303, headers=(
                ("Location", "/"),
                ("Set-Cookie", "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" % COOKIE))))
            return
        if path == PIN_PATH:
            await self.pin_submit(req, reader, writer, ip)
            return

        unlocked = cookie_valid(self.key, req.cookies().get(COOKIE, ""))
        token_path = path.startswith(TOKEN_PATH_PREFIXES) or path in TOKEN_PATHS
        if unlocked or token_path:
            # Without the cookie only a real websocket handshake may upgrade;
            # anything else is forced to a single request per connection.
            upgrade = is_websocket_handshake(req) and (unlocked or path == "/api/websocket")
            await self.proxy(req, reader, writer, ip, upgrade)
            return

        if req.method in ("GET", "HEAD") and "text/html" in (req.header("accept") or "text/html"):
            body = pin_page(safe_next(req.target))
            if req.method == "HEAD":
                body = b""
            writer.write(response(401, body, PAGE_HEADERS))
        else:
            writer.write(response(401, b"PIN required\n", (("Content-Type", "text/plain"),)))

    async def pin_submit(self, req, reader, writer, ip):
        if req.method != "POST":
            writer.write(response(303, headers=(("Location", "/"),)))
            return
        try:
            length = int(req.header("content-length") or "0")
        except ValueError:
            length = -1
        if req.header("transfer-encoding") or not 0 < length <= 4096:
            writer.write(response(400))
            return
        try:
            body = await asyncio.wait_for(reader.readexactly(length), 15)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            return
        form = parse_qs(body.decode("utf-8", "replace"))
        pin = (form.get("pin") or [""])[0]
        nxt = safe_next((form.get("next") or ["/"])[0])

        wait = self.limiter.locked_for(ip)
        if wait:
            log.warning("pin attempt from %s refused: locked for %ss", ip, wait)
            writer.write(response(429, pin_page(nxt, "Too many attempts. Try again in %d min." % ((wait + 59) // 60)),
                                  PAGE_HEADERS + (("Retry-After", str(wait)),)))
            return
        # Count the attempt before the (slow) hash check so parallel requests
        # cannot all slip past the limit; a correct PIN clears it again.
        self.limiter.fail(ip)
        ok = PIN_RE.match(pin) is not None and await asyncio.to_thread(check_pin, pin, self.pin_hash)
        if not ok:
            log.warning("wrong pin from %s", ip)
            await asyncio.sleep(1)
            writer.write(response(401, pin_page(nxt, "Wrong PIN."), PAGE_HEADERS))
            return
        self.limiter.success(ip)
        log.info("unlocked for %s", ip)
        cookie = "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (COOKIE, make_cookie(self.key, self.ttl), self.ttl)
        writer.write(response(303, headers=(("Location", nxt), ("Set-Cookie", cookie))))

    async def proxy(self, req, reader, writer, ip, upgrade):
        # Plain requests need a known body length so the gate can stop at the
        # request boundary. Browsers and the Companion app send Content-Length.
        length = 0
        if not upgrade:
            if req.header("transfer-encoding") is not None:
                writer.write(response(400))
                return
            try:
                length = int(req.header("content-length") or "0")
            except ValueError:
                length = -1
            if length < 0:
                writer.write(response(400))
                return
        try:
            up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(*self.upstream), 10)
        except (OSError, asyncio.TimeoutError):
            writer.write(response(502, b"Home Assistant is not reachable\n", (("Content-Type", "text/plain"),)))
            return
        lines = ["%s %s %s" % (req.method, req.target, req.version)]
        for k, v in req.headers:
            if k.lower() in HOP_HEADERS:
                continue
            if k.lower() == "cookie":
                # Home Assistant never sees the gate's own cookie.
                v = "; ".join(p.strip() for p in v.split(";") if not p.strip().startswith(COOKIE + "="))
                if not v:
                    continue
            lines.append("%s: %s" % (k, v))
        lines.append("X-Forwarded-For: %s" % ip)
        if upgrade:
            lines += ["Connection: Upgrade", "Upgrade: websocket"]
        else:
            lines.append("Connection: close")
        up_writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))

        async def pipe(src, dst):
            try:
                while True:
                    chunk = await src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass

        async def body(src, dst, length):
            # Forward exactly this request's body, never what follows it.
            try:
                while length > 0:
                    chunk = await src.read(min(length, 65536))
                    if not chunk:
                        break
                    dst.write(chunk)
                    await dst.drain()
                    length -= len(chunk)
            except (ConnectionError, asyncio.CancelledError):
                pass

        if upgrade:
            to_up = asyncio.ensure_future(pipe(reader, up_writer))
        else:
            to_up = asyncio.ensure_future(body(reader, up_writer, length))
        to_client = asyncio.ensure_future(pipe(up_reader, writer))
        # A plain request ends when upstream closes after its response, so no
        # second request can ride on this connection. A websocket ends when
        # either side goes away.
        if upgrade:
            await asyncio.wait({to_up, to_client}, return_when=asyncio.FIRST_COMPLETED)
        else:
            await to_client
        to_up.cancel()
        to_client.cancel()
        up_writer.close()


async def serve(gate, port):
    # Home Assistant may still hold the port right after it is moved to
    # loopback; keep retrying instead of crash-looping.
    for attempt in range(1, 10_000):
        try:
            server = await asyncio.start_server(gate.handle, port=port, limit=MAX_HEAD, reuse_address=True)
            break
        except OSError as err:
            if attempt == 1 or attempt % 30 == 0:
                log.warning("cannot listen on :%d yet (%s); retrying", port, err)
            await asyncio.sleep(2)
    log.info("listening on :%d -> %s:%d", port, *gate.upstream)
    async with server:
        await server.serve_forever()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if sys.argv[1:] == ["hash"]:
        pin = sys.stdin.readline().strip()
        if not PIN_RE.match(pin):
            sys.exit("PIN must be 6 to 32 digits")
        print(hash_pin(pin))
        print(secrets.token_urlsafe(32))
        return
    pin_hash = os.environ.get("PIN_GATE_PIN_HASH", "")
    key = os.environ.get("PIN_GATE_SECRET", "")
    if not pin_hash.startswith("pbkdf2:") or len(key) < 32:
        sys.exit("PIN_GATE_PIN_HASH / PIN_GATE_SECRET not set; run scripts/set-pin.sh")
    upstream_host, _, upstream_port = os.environ.get("PIN_GATE_UPSTREAM", "127.0.0.1:8124").rpartition(":")
    gate = Gate(pin_hash, key.encode(), upstream_host, int(upstream_port),
                int(os.environ.get("PIN_GATE_TTL", "86400")))
    asyncio.run(serve(gate, int(os.environ.get("PIN_GATE_PORT", "8123"))))


if __name__ == "__main__":
    main()
