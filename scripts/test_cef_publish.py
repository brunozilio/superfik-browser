"""Release packaging is local; tests never create a GitHub release."""

import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest

from publish_engine import package


class PublishTests(unittest.TestCase):
    def test_archive_keeps_framework_links_and_publishes_matching_checksums(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "engine"
            source.mkdir()
            (source / "superfik-engine.json").write_text('{"fixture":true}')
            (source / "binary").write_bytes(b"native fixture")
            (source / "Current").symlink_to("binary")
            archive, manifest, sums = package(source, root / "release", "test.1")
            with tarfile.open(archive) as bundle:
                link = bundle.getmember("superfik-cef-macos-arm64/Current")
                self.assertTrue(link.issym())
                self.assertEqual(link.linkname, "binary")
            expected = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                               for path in (archive, manifest))
            self.assertEqual(sums.read_text(), expected)
            with self.assertRaisesRegex(ValueError, "already exists"):
                package(source, root / "release", "test.1")

    def test_tag_cannot_create_a_path_outside_release_directory(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "tag"):
                package(Path(root), Path(root) / "release", "../../outside")


if __name__ == "__main__":
    unittest.main()
