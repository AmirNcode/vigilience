"""Unit tests for scripts/homelab_deploy.py (manifest, rendering, CLI flow).

Run via tests/homelab-deploy-test.sh (stdlib only, no Docker or SSH needed).
"""

import os
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

    def test_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ManifestError):
                hd.load_manifest(Path(tmp))


if __name__ == "__main__":
    unittest.main(verbosity=1)
