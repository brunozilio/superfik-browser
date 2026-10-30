"""The build's staged layout must be accepted by the artifact validator."""

import json
from pathlib import Path
import tempfile
import unittest

from build_cef import stage
from cef_artifact import CEF_COMMIT, CEF_VERSION, FRAMEWORK, build_identity, validate
from cef_pipeline import load_lock, seal_distribution


class DistributionTests(unittest.TestCase):
    def test_staged_release_round_trips_through_validation(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            distribution = root / "distribution"
            for name in ("include", "cmake", "libcef_dll", f"Release/{FRAMEWORK}"):
                (distribution / name).mkdir(parents=True)
            for name in ("CMakeLists.txt", "CREDITS.html"):
                (distribution / name).write_text("fixture\n")
            (distribution / "include/cef_version.h").write_text(
                f'#define CEF_VERSION "{CEF_VERSION}"\n'
                f'#define CEF_COMMIT_HASH "{CEF_COMMIT}"\n'
            )
            (distribution / "Release" / FRAMEWORK / "Chromium Embedded Framework").write_bytes(b"fixture")
            archive = root / "fixture.tar.bz2"
            archive.write_bytes(b"fixture archive")
            staged = root / "staged"
            stage(distribution, staged)
            lock = load_lock()
            seal_distribution(staged, lock["patches"], lock, archive)
            self.assertEqual(validate(staged, lock["patches"], build_identity(lock)), staged.resolve())
            self.assertTrue((staged / FRAMEWORK).is_dir())
            self.assertFalse((staged / "Release").exists())
            metadata = json.loads((staged / "archive.json").read_text())
            self.assertEqual(metadata["type"], "minimal")
            self.assertEqual(len(metadata["sha1"]), 40)
            with self.assertRaisesRegex(ValueError, "already exists"):
                stage(distribution, staged)
            changed = dict(build_identity(lock), gn_defines="different build")
            with self.assertRaisesRegex(ValueError, "build configuration"):
                validate(staged, lock["patches"], changed)


if __name__ == "__main__":
    unittest.main()
