"""Artifact acceptance tests; run with python3 -m unittest discover -s scripts."""

import tempfile
import unittest
import json
from pathlib import Path

from cef_artifact import CEF_COMMIT, CEF_VERSION, FRAMEWORK, digest, validate


class ArtifactTests(unittest.TestCase):
    def fixture(self, directory):
        (directory / "include").mkdir()
        (directory / "include/cef_version.h").write_text(
            f'#define CEF_VERSION "{CEF_VERSION}"\n'
            f'#define CEF_COMMIT_HASH "{CEF_COMMIT}"\n'
        )
        (directory / "archive.json").write_text(json.dumps({
            "name": f"cef_binary_{CEF_VERSION}_macosarm64_minimal.tar.bz2",
            "type": "minimal", "sha1": "a" * 40,
        }))
        (directory / FRAMEWORK).mkdir()
        (directory / FRAMEWORK / "Chromium Embedded Framework").write_bytes(b"fixture")
        data = {
            "schema": 1, "cef_commit": CEF_COMMIT,
            "target": "aarch64-apple-darwin",
            "patches": [{"name": "test.patch", "sha256": "a" * 64}],
            "files": {p.relative_to(directory).as_posix(): digest(p)
                      for p in directory.rglob("*") if p.is_file()},
        }
        (directory / "superfik-engine.json").write_text(json.dumps(data))

    def test_accepts_complete_distribution_and_rejects_binary_tampering(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve()
            self.fixture(directory)
            self.assertEqual(validate(directory), directory)
            (directory / FRAMEWORK / "Chromium Embedded Framework").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksums"):
                validate(directory)

    def test_rejects_untracked_files(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve()
            self.fixture(directory)
            (directory / "unexpected.dylib").write_bytes(b"untracked")
            with self.assertRaisesRegex(ValueError, "checksums"):
                validate(directory)

    def test_another_patch_series_is_not_the_requested_engine(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve()
            self.fixture(directory)
            with self.assertRaisesRegex(ValueError, "engine lock"):
                validate(directory, [{"name": "different.patch", "sha256": "b" * 64}])

    def test_framework_symlink_cannot_be_retargeted_even_to_identical_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root).resolve()
            self.fixture(directory)
            for name in ("a", "b"):
                (directory / name).write_bytes(b"same bytes")
            alias = directory / "Alias"
            alias.symlink_to("a")
            manifest = directory / "superfik-engine.json"
            data = json.loads(manifest.read_text())
            data["files"].update({name: digest(directory / name) for name in ("a", "b", "Alias")})
            data["symlinks"] = {"Alias": "a"}
            manifest.write_text(json.dumps(data))
            validate(directory)
            alias.unlink()
            alias.symlink_to("b")
            with self.assertRaisesRegex(ValueError, "symlink"):
                validate(directory)

    def test_missing_distribution_never_falls_back_to_download(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "manifest"):
                validate(Path(root))

    def test_stock_distribution_is_not_a_custom_engine(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "superfik-engine.json").write_text(
                '{"schema":1,"cef_commit":"wrong","target":"aarch64-apple-darwin",'
                '"files":{},"patches":[]}'
            )
            with self.assertRaises(ValueError):
                validate(directory)
