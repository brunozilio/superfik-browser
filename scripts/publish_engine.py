"""Package a validated local engine and upload a draft GitHub Release."""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from cef_artifact import build_identity, digest, probe, validate
from cef_pipeline import ROOT, load_lock


def package(directory, destination, tag):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}", tag):
        raise ValueError("release tag must contain only letters, digits, dots, underscores or hyphens")
    if destination.exists():
        raise ValueError("release output already exists; preserve or inspect it before retrying")
    if destination.resolve().is_relative_to(directory.resolve()):
        raise ValueError("release output cannot be inside the engine distribution")
    destination.mkdir(parents=True)
    archive = destination / f"superfik-cef-macos-arm64-{tag}.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(directory, arcname="superfik-cef-macos-arm64")
    if archive.stat().st_size >= 2 * 1024**3:
        raise ValueError("archive exceeds GitHub's per-asset limit; do not upload it unsplit")
    manifest = destination / "superfik-engine.json"
    shutil.copy2(directory / manifest.name, manifest)
    sums = destination / "SHA256SUMS"
    sums.write_text("".join(f"{digest(path)}  {path.name}\n" for path in (archive, manifest)))
    return archive, manifest, sums


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", default="brunozilio/superfik-browser")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args()
    lock = load_lock()
    directory = validate(args.distribution, lock["patches"], build_identity(lock))
    probe(directory)
    destination = args.output or ROOT / "target/releases" / args.tag
    assets = package(directory, destination, args.tag)
    if args.package_only:
        print(destination)
        return
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("commit and push the engine source before creating its release")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    notes = destination / "RELEASE_NOTES.md"
    notes.write_text(
        f"Experimental engine candidate.\n\nCEF: `{lock['cef_version']}`.\n"
        f"Chromium: `{lock['chromium_commit']}`.\nSource: `{commit}`.\n\n"
        "Manifest, patch hashes and native marker were checked locally.\n"
        "Browser compatibility and isolation still require review before publication.\n"
    )
    subprocess.run([
        "gh", "release", "create", args.tag, *(str(path) for path in assets),
        "--repo", args.repo, "--target", commit, "--draft", "--title", args.tag,
        "--notes-file", str(notes),
    ], check=True, cwd=ROOT)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
