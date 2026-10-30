"""Validate a custom CEF distribution before Cargo can select/download CEF.

The manifest is provenance, not a signature. Only use artifacts from a trusted
builder. The framework must be validated before codesigning changes its bytes.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

CEF_COMMIT = "14c5a089e8452874cb1a556dc3fde26ed2d87723"
CEF_VERSION = "154.0.34+g14c5a08+chromium-154.0.8037.98"
TARGET = "aarch64-apple-darwin"
FRAMEWORK = "Chromium Embedded Framework.framework"
ENGINE_VERSION_ENTRY = 0x535546
ENGINE_ABI = 1


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def build_identity(lock):
    return {key: lock[key] for key in (
        "chromium_ref", "chromium_commit", "depot_tools_commit", "gn_defines",
    )}


def validate(directory, expected_patches=None, expected_build=None):
    directory = directory.resolve(strict=True)
    manifest = directory / "superfik-engine.json"
    if not manifest.is_file():
        raise ValueError("custom engine manifest is missing")
    data = json.loads(manifest.read_text())
    if (data.get("schema"), data.get("cef_commit"), data.get("target")) != (
        1, CEF_COMMIT, TARGET
    ):
        raise ValueError("unsupported engine schema, CEF revision or target")
    patches = data.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("custom engine must identify its patches")
    if expected_patches is not None and patches != expected_patches:
        raise ValueError("artifact patch series differs from engine lock")
    if expected_build is not None and data.get("build") != expected_build:
        raise ValueError("artifact build configuration differs from engine lock")
    for patch in patches:
        if not isinstance(patch, dict) or not patch.get("name"):
            raise ValueError("invalid patch identity")
        checksum = patch.get("sha256", "")
        if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise ValueError("invalid patch checksum")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("artifact file checksums are missing")
    # Include all regular files, following internal framework symlinks only.
    actual = {}
    links = {}
    for path in directory.rglob("*"):
        if not path.resolve().is_relative_to(directory):
            raise ValueError("artifact symlink escapes distribution")
        if path.is_symlink():
            links[path.relative_to(directory).as_posix()] = path.readlink().as_posix()
        if path.is_file() and path != manifest:
            actual[path.relative_to(directory).as_posix()] = digest(path)
    if actual != files:
        raise ValueError("artifact contents do not match manifest checksums")
    if links != data.get("symlinks", {}):
        raise ValueError("artifact symlinks do not match manifest")
    header = directory / "include/cef_version.h"
    if f'#define CEF_VERSION "{CEF_VERSION}"' not in header.read_text():
        raise ValueError("CEF header version does not match pinned ABI")
    if CEF_COMMIT not in header.read_text():
        raise ValueError("CEF header commit does not match pinned revision")
    archive = json.loads((directory / "archive.json").read_text())
    if archive.get("name") != f"cef_binary_{CEF_VERSION}_macosarm64_minimal.tar.bz2":
        raise ValueError("archive metadata does not match pinned ABI")
    if archive.get("type") != "minimal" or not re.fullmatch("[0-9a-f]{40}", archive.get("sha1", "")):
        raise ValueError("archive metadata is incompatible with cef-dll-sys")
    binary = directory / FRAMEWORK / "Chromium Embedded Framework"
    if not binary.is_file():
        raise ValueError("CEF framework binary is missing")
    return directory


def probe(directory):
    """Verify the compiled native marker without launching a browser/profile."""
    import ctypes
    binary = directory / FRAMEWORK / "Chromium Embedded Framework"
    library = ctypes.CDLL(str(binary))
    version = library.cef_version_info
    version.argtypes = [ctypes.c_int]
    version.restype = ctypes.c_int
    if version(ENGINE_VERSION_ENTRY) != ENGINE_ABI:
        raise ValueError("framework is missing the Superfik native engine marker")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    lock_path = Path(__file__).resolve().parent.parent / "native/cef/engine.lock.json"
    lock = json.loads(lock_path.read_text())
    directory = validate(args.distribution, lock["patches"], build_identity(lock))
    if args.probe:
        probe(directory)
    print(directory)


if __name__ == "__main__":
    main()
