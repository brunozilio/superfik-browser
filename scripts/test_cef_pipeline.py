"""Public pipeline tests use local Git repositories, never network/build tools."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from cef_pipeline import apply_series, load_lock, patch_records
from cef_artifact import digest


class PipelineTests(unittest.TestCase):
    def test_repository_patch_series_matches_pinned_checksums(self):
        from cef_pipeline import PATCHES
        records = patch_records(PATCHES, load_lock())
        self.assertTrue(records)

    def test_unreviewed_patch_change_is_rejected_before_touching_source(self):
        with tempfile.TemporaryDirectory() as root:
            patches = Path(root)
            patch = patches / "edit.patch"
            patch.write_text("unreviewed contents")
            with self.assertRaisesRegex(ValueError, "checksum"):
                patch_records(patches, {"patches": [{
                    "name": "edit.patch", "repository": "cef", "sha256": "0" * 64,
                }]})

    def test_patch_cannot_escape_its_reviewed_directory(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            patches = root / "patches"
            patches.mkdir()
            outside = root / "outside.patch"
            outside.write_text("outside")
            with self.assertRaisesRegex(ValueError, "escapes"):
                patch_records(patches, {"patches": [{
                    "name": "../outside.patch", "repository": "cef", "sha256": digest(outside),
                }]})

    def test_patch_series_is_applied_once_and_changes_are_verified_on_resume(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q", str(source)], check=True)
            original = source / "value.txt"
            original.write_text("before\n")
            subprocess.run(["git", "-C", str(source), "add", "."], check=True)
            subprocess.run(["git", "-C", str(source), "-c", "user.name=Fixture",
                            "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial"], check=True)
            patches = root / "patches"
            patches.mkdir()
            (patches / "change.patch").write_text(
                "diff --git a/value.txt b/value.txt\n--- a/value.txt\n+++ b/value.txt\n"
                "@@ -1 +1 @@\n-before\n+after\n"
            )
            lock = {"patches": [{"name": "change.patch", "repository": "cef",
                                  "sha256": digest(patches / "change.patch")}]}
            apply_series({"cef": source}, patches, lock)
            self.assertEqual(original.read_text(), "after\n")
            (patches / "extension.patch").write_text(
                "diff --git a/value.txt b/value.txt\n--- a/value.txt\n+++ b/value.txt\n"
                "@@ -1 +1 @@\n-after\n+extended\n"
            )
            lock["patches"].append({"name": "extension.patch", "repository": "cef",
                                    "sha256": digest(patches / "extension.patch")})
            apply_series({"cef": source}, patches, lock)
            self.assertEqual(original.read_text(), "extended\n")
            # CEF's translator creates untracked C API headers during build.
            # They are not edits to reviewed source files.
            (source / "generated.h").write_text("generated output\n")
            apply_series({"cef": source}, patches, lock)
            self.assertEqual(original.read_text(), "extended\n")
            original.write_text("unrelated edit\n")
            with self.assertRaisesRegex(ValueError, "diverged"):
                apply_series({"cef": source}, patches, lock)


if __name__ == "__main__":
    unittest.main()
