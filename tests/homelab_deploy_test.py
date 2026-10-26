"""Unit tests for scripts/homelab_deploy.py (manifest, rendering, CLI flow).

Run via tests/homelab-deploy-test.sh (stdlib only, no Docker or SSH needed).
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import homelab_deploy as hd  # noqa: E402
from homelab_deploy import ManifestError  # noqa: E402


def app_dir(tmp, manifest, files=()):
    d = Path(tmp)
    (d / "homelab.yaml").write_text(manifest)
    for f in files:
        (d / f).write_text("x\n")
    return d


DOCKER = "name: notes\nport: 8201\ncontainer_port: 3000\n"


class ParseFlatYaml(unittest.TestCase):
    def test_parse_flat_yaml_strips_comments_and_quotes(self):
        self.assertEqual(
            hd.parse_flat_yaml('name: "notes"  # c\n\nport: 8201\n'),
            {"name": "notes", "port": "8201"},
        )

    def test_parse_flat_yaml_rejects_nesting(self):
        with self.assertRaises(ManifestError):
            hd.parse_flat_yaml("a:\n  b: 1\n")

    def test_parse_flat_yaml_rejects_list(self):
        with self.assertRaises(ManifestError):
            hd.parse_flat_yaml("- x\n")

    def test_parse_flat_yaml_rejects_duplicate(self):
        with self.assertRaises(ManifestError):
            hd.parse_flat_yaml("a: 1\na: 2\n")

    def test_parse_flat_yaml_rejects_missing_colon(self):
        with self.assertRaises(ManifestError):
            hd.parse_flat_yaml("just words\n")


class LoadManifest(unittest.TestCase):
    def load(self, manifest, files=()):
        with tempfile.TemporaryDirectory() as tmp:
            return hd.load_manifest(app_dir(tmp, manifest, files))

    def assertInvalid(self, manifest, files=("Dockerfile",), contains=None):
        with self.assertRaises(ManifestError) as cm:
            self.load(manifest, files)
        if contains:
            self.assertIn(contains, str(cm.exception))

    def test_docker_kind_inferred_from_dockerfile(self):
        m = self.load(DOCKER, ["Dockerfile"])
        self.assertEqual(m.kind, "docker")
        self.assertEqual(m.name, "notes")
        self.assertEqual(m.port, 8201)
        self.assertEqual(m.container_port, 3000)
        self.assertEqual(m.icon, "mdi:application")
        self.assertEqual(m.memory, "512m")
        self.assertEqual(m.health_path, "/")
        self.assertEqual(m.service, "notes")
        self.assertIsNone(m.data)

    def test_compose_kind_inferred(self):
        m = self.load(DOCKER, ["compose.yaml", "Dockerfile"])
        self.assertEqual(m.kind, "compose")

    def test_compose_service_override(self):
        m = self.load(DOCKER + "service: web\n", ["compose.yaml"])
        self.assertEqual(m.service, "web")

    def test_static_requires_explicit_kind(self):
        self.assertInvalid("name: site\nport: 8202\n", files=(), contains="kind: static")

    def test_static_container_port_is_80(self):
        m = self.load("name: site\nport: 8202\nkind: static\n")
        self.assertEqual(m.kind, "static")
        self.assertEqual(m.container_port, 80)
        self.assertEqual(m.dist, "dist")

    def test_static_rejects_container_port(self):
        self.assertInvalid("name: site\nport: 8202\nkind: static\ncontainer_port: 80\n", files=())

    def test_port_out_of_range(self):
        for p in ("8199", "8300", "abc"):
            self.assertInvalid(f"name: notes\nport: {p}\ncontainer_port: 3000\n")

    def test_bad_name(self):
        for n in ("Notes", "9x", "a_b", ""):
            self.assertInvalid(f"name: {n}\nport: 8201\ncontainer_port: 3000\n")

    def test_missing_required(self):
        self.assertInvalid("port: 8201\ncontainer_port: 3000\n", contains="name")

    def test_unknown_key(self):
        self.assertInvalid(DOCKER + "colour: red\n", contains="colour")

    def test_data_only_for_docker(self):
        self.assertInvalid(DOCKER + "data: /app/data\n", files=("compose.yaml",))
        m = self.load(DOCKER + "data: /app/data\n", ["Dockerfile"])
        self.assertEqual(m.data, "/app/data")

    def test_data_must_be_absolute(self):
        self.assertInvalid(DOCKER + "data: app/data\n")

    def test_dist_rejects_dotdot(self):
        self.assertInvalid("name: site\nport: 8202\nkind: static\ndist: ../out\n", files=())

    def test_missing_container_port_for_docker(self):
        self.assertInvalid("name: notes\nport: 8201\n", contains="container_port")

    def test_bad_icon_memory_health(self):
        self.assertInvalid(DOCKER + "icon: notebook\n")
        self.assertInvalid(DOCKER + "memory: lots\n")
        self.assertInvalid(DOCKER + "health_path: healthz\n")
        self.assertInvalid(DOCKER + "health_path: /h?x=1\n")
        self.assertEqual(self.load(DOCKER + "health_path: /api/v1/health\n", ["Dockerfile"]).health_path, "/api/v1/health")

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ManifestError):
                hd.load_manifest(Path(tmp))


LAN = "192.0.2.10"


def manifest(**kw):
    base = dict(name="notes", port=8201, kind="docker", icon="mdi:application",
                container_port=3000, health_path="/", memory="512m", data=None,
                build=None, dist="dist", service="notes")
    base.update(kw)
    return hd.Manifest(**base)


def cfg_port(published, host_ip=LAN, target=3000):
    p = {"mode": "ingress", "target": target, "published": str(published), "protocol": "tcp"}
    if host_ip is not None:
        p["host_ip"] = host_ip
    return p


class RenderCompose(unittest.TestCase):
    def test_render_docker(self):
        doc = hd.render_compose(manifest(), LAN, None)
        self.assertEqual(doc["name"], "app-notes")
        svc = doc["services"]["notes"]
        self.assertEqual(svc["ports"], [{"host_ip": LAN, "published": "8201", "target": 3000, "protocol": "tcp"}])
        self.assertEqual(svc["labels"], {
            "homelab.app.name": "notes",
            "homelab.app.url": "http://192.0.2.10:8201",
            "homelab.app.icon": "mdi:application",
            "homelab.app.port": "8201",
            "homelab.app.health": "/",
        })
        self.assertEqual(svc["container_name"], "app-notes")
        self.assertEqual(svc["image"], "homelab-app-notes:local")
        self.assertEqual(svc["build"], {"context": "."})
        self.assertEqual(svc["restart"], "unless-stopped")
        self.assertEqual(svc["mem_limit"], "512m")
        self.assertNotIn("env_file", svc)
        self.assertNotIn("volumes", doc)

    def test_render_env_file_optional(self):
        env = "/home/u/.config/homelab/notes.env"
        svc = hd.render_compose(manifest(), LAN, env)["services"]["notes"]
        self.assertEqual(svc["env_file"], [{"path": env, "required": False}])

    def test_render_data_volume(self):
        doc = hd.render_compose(manifest(data="/app/data"), LAN, None)
        self.assertEqual(doc["services"]["notes"]["volumes"], ["data:/app/data"])
        self.assertEqual(doc["volumes"], {"data": {}})

    def test_render_static(self):
        m = manifest(name="site", kind="static", container_port=80, service="site")
        svc = hd.render_compose(m, LAN, None)["services"]["site"]
        self.assertEqual(svc["build"], {"context": ".homelab/static"})
        self.assertEqual(svc["ports"][0]["target"], 80)
        df = hd.static_dockerfile(m)
        self.assertTrue(df.startswith("FROM nginx:1.27.3-alpine"))
        self.assertIn("COPY site/ /usr/share/nginx/html/", df)

    def test_render_compose_override_only_touches_service(self):
        m = manifest(kind="compose", service="web")
        doc = hd.render_compose(m, LAN, "/x.env")
        self.assertEqual(set(doc), {"services"})
        self.assertEqual(set(doc["services"]), {"web"})
        self.assertEqual(set(doc["services"]["web"]), {"ports", "restart", "mem_limit", "labels"})


class CheckRendered(unittest.TestCase):
    m = manifest(kind="compose", service="web")

    def cfg(self, **services):
        return {"name": "app-notes", "services": services}

    def test_check_ok_for_named_volume_db(self):
        cfg = self.cfg(
            web={"ports": [cfg_port(8201)]},
            db={"volumes": [{"type": "volume", "source": "pg", "target": "/var/lib/postgresql/data"}]},
        )
        self.assertEqual(hd.check_rendered(cfg, self.m, LAN), [])

    def test_check_rejects_extra_port(self):
        cfg = self.cfg(web={"ports": [cfg_port(8201)]}, db={"ports": [cfg_port(5432, target=5432)]})
        errs = hd.check_rendered(cfg, self.m, LAN)
        self.assertTrue(any("db" in e and "5432" in e for e in errs), errs)

    def test_check_rejects_wildcard_bind(self):
        for host_ip in (None, "0.0.0.0", ""):
            cfg = self.cfg(web={"ports": [cfg_port(8201, host_ip=host_ip)]})
            errs = hd.check_rendered(cfg, self.m, LAN)
            self.assertTrue(any("LAN IP" in e for e in errs), (host_ip, errs))

    def test_check_rejects_second_port_on_service(self):
        cfg = self.cfg(web={"ports": [cfg_port(8201), cfg_port(8202)]})
        self.assertTrue(hd.check_rendered(cfg, self.m, LAN))

    def test_check_rejects_bind_mount(self):
        cfg = self.cfg(web={"ports": [cfg_port(8201)],
                            "volumes": [{"type": "bind", "source": "/home/linus/apps/notes/data", "target": "/data"}]})
        errs = hd.check_rendered(cfg, self.m, LAN)
        self.assertTrue(any("bind-mounts /home/linus/apps/notes/data" in e for e in errs), errs)

    def test_check_rejects_privileged(self):
        cfg = self.cfg(web={"ports": [cfg_port(8201)], "privileged": True})
        self.assertTrue(any("privileged" in e for e in hd.check_rendered(cfg, self.m, LAN)))

    def test_check_rejects_host_network(self):
        cfg = self.cfg(web={"ports": [cfg_port(8201)]}, db={"network_mode": "host"})
        self.assertTrue(any("host" in e for e in hd.check_rendered(cfg, self.m, LAN)))

    def test_check_missing_service(self):
        errs = hd.check_rendered(self.cfg(api={}), self.m, LAN)
        self.assertTrue(any("service web not found" in e for e in errs), errs)


class PortConflict(unittest.TestCase):
    def test_port_conflict_other_app(self):
        msg = hd.find_port_conflict(manifest(), {"todo": 8201}, True)
        self.assertIn("todo", msg)

    def test_port_redeploy_same_app_ok(self):
        self.assertIsNone(hd.find_port_conflict(manifest(), {"notes": 8201}, True))

    def test_port_taken_by_non_app(self):
        self.assertIn("in use", hd.find_port_conflict(manifest(), {}, True))

    def test_port_free(self):
        self.assertIsNone(hd.find_port_conflict(manifest(), {"todo": 8202}, False))


def done(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class FakeRunner:
    """Records commands; answers the remote facts / config / health calls."""

    def __init__(self, facts=None, config=None, health="200", up_rc=0):
        self.calls = []
        self.facts = {"HOME": "/home/u", "LAN_IP": LAN} if facts is None else facts
        self.config = config
        self.health = health
        self.up_rc = up_rc

    def run(self, argv, *, input=None, check=True, cwd=None):
        self.calls.append(("run", argv, input))
        last = argv[-1]
        if input and "OWNER=" in input:
            return done("".join(f"{k}={v}\n" for k, v in self.facts.items()))
        if "config --format json" in last:
            return done(json.dumps(self.config))
        if "curl" in last:
            return done(self.health)
        return done()

    def stream(self, argv, *, cwd=None):
        self.calls.append(("stream", argv, None))
        return self.up_rc if " up " in argv[-1] else 0

    def kinds(self):
        out = []
        for kind, argv, inp in self.calls:
            last = argv[-1]
            if argv[0] == "rsync":
                out.append("rsync-homelab" if "/.homelab/" in argv[-2] else "rsync-source")
            elif inp and "OWNER=" in inp:
                out.append("facts")
            elif "mkdir" in last:
                out.append("mkdir")
            elif "config --format json" in last:
                out.append("config")
            elif " up " in last:
                out.append("up")
            elif "curl" in last:
                out.append("health")
            else:
                out.append(last)
        return out


def ok_config(service="notes", port=8201):
    return {"name": "app-notes", "services": {service: {"ports": [cfg_port(port)]}}}


class Deploy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = app_dir(self.tmp.name, DOCKER, ["Dockerfile"])

    def tearDown(self):
        self.tmp.cleanup()

    def deploy(self, runner, force=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = hd.deploy(self.dir, "mint", ".config/vigilience/production.env", runner, force=force)
        return rc, out.getvalue(), err.getvalue()

    def test_rsync_excludes_secrets(self):
        args = hd.rsync_args(self.dir, "mint", "apps/notes/")
        self.assertIn("--exclude=.env*", args)
        self.assertIn("--exclude=.git", args)
        self.assertEqual(args[-1], "mint:apps/notes/")
        self.assertTrue(args[-2].endswith("/"))

    def test_deploy_happy_path_order(self):
        r = FakeRunner(config=ok_config())
        rc, out, err = self.deploy(r)
        self.assertEqual(rc, 0, err)
        self.assertEqual(r.kinds(), ["facts", "mkdir", "rsync-source", "rsync-homelab", "config", "up", "health"])
        self.assertIn("http://192.0.2.10:8201", out)

    def test_deploy_refuses_other_source(self):
        r = FakeRunner(facts={"HOME": "/home/u", "LAN_IP": LAN, "SOURCE": "otherhost:/x"}, config=ok_config())
        rc, out, err = self.deploy(r)
        self.assertEqual(rc, 1)
        self.assertIn("otherhost:/x", err)
        self.assertIn("--force", err)
        self.assertNotIn("rsync-source", r.kinds())

    def test_deploy_force_replaces(self):
        r = FakeRunner(facts={"HOME": "/home/u", "LAN_IP": LAN, "SOURCE": "otherhost:/x"}, config=ok_config())
        rc, out, err = self.deploy(r, force=True)
        self.assertEqual(rc, 0, err)
        self.assertIn("up", r.kinds())

    def test_deploy_missing_lan_ip(self):
        rc, out, err = self.deploy(FakeRunner(facts={"HOME": "/home/u"}))
        self.assertEqual(rc, 1)
        self.assertIn("VIG_LAN_IP", err)

    def test_deploy_port_conflict(self):
        r = FakeRunner(facts={"HOME": "/home/u", "LAN_IP": LAN, "OWNER": "todo=8201", "LISTENING": "1"})
        rc, out, err = self.deploy(r)
        self.assertEqual(rc, 1)
        self.assertIn("todo", err)
        self.assertEqual(r.kinds(), ["facts"])

    def test_deploy_reports_check_violations(self):
        cfg = ok_config()
        cfg["services"]["db"] = {"ports": [cfg_port(5432, host_ip="0.0.0.0", target=5432)]}
        r = FakeRunner(config=cfg)
        rc, out, err = self.deploy(r)
        self.assertEqual(rc, 1)
        self.assertIn("5432", err)
        self.assertNotIn("up", r.kinds())

    def test_deploy_health_fail_hint(self):
        rc, out, err = self.deploy(FakeRunner(config=ok_config(), health="000"))
        self.assertEqual(rc, 1)
        self.assertIn("0.0.0.0:3000", err)

    def test_deploy_up_failure(self):
        rc, out, err = self.deploy(FakeRunner(config=ok_config(), up_rc=17))
        self.assertEqual(rc, 1)

    def test_env_file_passed_when_present(self):
        r = FakeRunner(facts={"HOME": "/home/u", "LAN_IP": LAN, "ENV_EXISTS": "1"}, config=ok_config())
        rc, _, err = self.deploy(r)
        self.assertEqual(rc, 0, err)
        up = [a for k, a, _ in r.calls if k == "stream"][0][-1]
        self.assertIn("--env-file /home/u/.config/homelab/notes.env", up)

    def test_static_stages_site_without_source_rsync(self):
        d = Path(self.tmp.name) / "site"
        (d / "dist").mkdir(parents=True)
        (d / "homelab.yaml").write_text("name: site\nport: 8202\nkind: static\n")
        (d / "dist" / "index.html").write_text("hi")
        r = FakeRunner(config=ok_config("site", 8202))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = hd.deploy(d, "mint", "env", r)
        self.assertEqual(rc, 0, err.getvalue())
        self.assertNotIn("rsync-source", r.kinds())

    def test_static_missing_index(self):
        d = Path(self.tmp.name) / "site"
        d.mkdir()
        (d / "homelab.yaml").write_text("name: site\nport: 8202\nkind: static\n")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = hd.deploy(d, "mint", "env", FakeRunner())
        self.assertEqual(rc, 1)
        self.assertIn("index.html", err.getvalue())


class Main(unittest.TestCase):
    def test_down_rejects_bad_name(self):
        r = FakeRunner()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(hd.main(["down", "x;rm"], runner=r), 1)
        self.assertEqual(r.calls, [])

    def test_down_uses_project_name(self):
        r = FakeRunner()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(hd.main(["down", "notes"], runner=r), 0)
        self.assertIn("docker compose -p app-notes down", r.calls[0][1][-1])


if __name__ == "__main__":
    unittest.main(verbosity=1)
