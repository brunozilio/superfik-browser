"""Prepare or build the pinned macOS ARM64 CEF; never discard source edits."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from cef_pipeline import (
    PATCHES, ROOT, apply_series, load_lock, output, patch_records, run,
    seal_distribution,
)
from cef_artifact import build_identity, probe, validate


def environment(work, lock):
    env = dict(os.environ)
    env["PATH"] = str(work / "depot_tools") + os.pathsep + env["PATH"]
    env["DEPOT_TOOLS_UPDATE"] = "0"
    env["DEPOT_TOOLS_METRICS"] = "0"
    env["DEPOT_TOOLS_COLLECT_METRICS"] = "0"
    env["GN_DEFINES"] = lock["gn_defines"]
    env["CEF_USE_GN"] = "1"
    # Select full Xcode only for this build; do not change xcode-select.
    env.setdefault("DEVELOPER_DIR", "/Applications/Xcode.app/Contents/Developer")
    return env


def doctor(env):
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise ValueError("this engine build currently requires macOS Apple Silicon")
    if sys.version_info < (3, 9):
        raise ValueError("Python 3.9 or newer is required")
    run(["git", "--version"], env=env)
    run(["xcodebuild", "-version"], env=env)
    run(["xcrun", "--sdk", "macosx", "--show-sdk-version"], env=env)
    run(["xcrun", "metal", "--version"], env=env)


def pinned_checkout(path, url, revision):
    if not path.exists():
        run(["git", "clone", "--filter=blob:none", url, path])
    elif output(["git", "remote", "get-url", "origin"], path) != url:
        raise ValueError(f"unexpected source repository: {path}")
    if output(["git", "status", "--porcelain"], path):
        raise ValueError(f"source has local edits: {path}")
    if output(["git", "rev-parse", "HEAD"], path) != revision:
        run(["git", "fetch", "origin", revision], cwd=path)
        run(["git", "checkout", "--detach", revision], cwd=path)


def arguments(work, lock):
    return [sys.executable, "-u", str(work / "cef/tools/automate/automate-git.py"),
            f"--download-dir={work}", f"--depot-tools-dir={work / 'depot_tools'}",
            f"--checkout={lock['cef_commit']}",
            # Upstream's no-history mode requires refs/tags/X syntax. The
            # resolved HEAD is separately checked against chromium_commit.
            f"--chromium-checkout={lock['chromium_ref']}",
            f"--chromium-url={lock['chromium_url']}",
            "--arm64-build", "--no-debug-build", "--no-depot-tools-update",
            "--no-chromium-history", "--with-pgo-profiles"]


def bootstrap_python(work, env):
    if not (work / "depot_tools/python3_bin_reldir.txt").is_file():
        run(["bash", "-c", 'source "$1"; bootstrap_python3', "bootstrap",
             work / "depot_tools/bootstrap_python3"], cwd=work, env=env)


def prepare(work, lock, env):
    work.mkdir(parents=True, exist_ok=True)
    if (work / "chromium/superfik-patches.json").exists():
        raise ValueError("sources already patched; use build instead of prepare")
    pinned_checkout(work / "depot_tools",
                    "https://chromium.googlesource.com/chromium/tools/depot_tools.git",
                    lock["depot_tools_commit"])
    pinned_checkout(work / "cef", "https://github.com/chromiumembedded/cef.git", lock["cef_commit"])
    bootstrap_python(work, env)
    run(arguments(work, lock) + ["--no-cef-update", "--no-build", "--no-distrib"],
        cwd=work, env=env)
    verify_sources(work, lock)


def verify_sources(work, lock):
    source = work / "chromium/src"
    repositories = {"cef": source / "cef", "chromium": source}
    for name, path in repositories.items():
        expected = lock["cef_commit"] if name == "cef" else lock["chromium_commit"]
        if output(["git", "rev-parse", "HEAD"], path) != expected:
            raise ValueError(f"{name} revision differs from engine lock")
    if output(["git", "rev-parse", "HEAD"], work / "depot_tools") != lock["depot_tools_commit"]:
        raise ValueError("depot_tools revision differs from engine lock")
    return repositories


def stage(distribution, destination):
    if destination.exists():
        raise ValueError(f"output already exists; preserve or validate it: {destination}")
    destination.mkdir(parents=True)
    # Match download-cef's flattened layout rather than its archive layout.
    for name in ("include", "cmake", "libcef_dll", "CMakeLists.txt", "CREDITS.html"):
        source = distribution / name
        if source.is_dir():
            shutil.copytree(source, destination / name, symlinks=True)
        else:
            shutil.copy2(source, destination / name)
    for source in (distribution / "Release").iterdir():
        target = destination / source.name
        if source.is_symlink():
            target.symlink_to(source.readlink())
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)


def build(work, destination, lock, env):
    if not patch_records(PATCHES, lock):
        raise ValueError("native patch series is empty; no custom engine can be built yet")
    repositories = verify_sources(work, lock)
    bootstrap_python(work, env)
    # Also support a checkout prepared before PGO profiles were enabled in
    # automate-git. The pinned Chromium script verifies its profile revision.
    run([sys.executable, repositories["chromium"] / "tools/update_pgo_profiles.py",
         "--target=mac-arm", "update", "--gs-url-base=chromium-optimization-profiles/pgo_profiles"],
        cwd=repositories["chromium"], env=env)
    run([sys.executable, repositories["chromium"] / "v8/tools/builtins-pgo/download_profiles.py",
         "download", "--depot-tools", work / "depot_tools", "--check-v8-revision", "--quiet"],
        cwd=repositories["chromium"], env=env)
    ledger = repositories["chromium"].parent / "superfik-patches.json"
    if not ledger.exists():
        # Bootstrap CEF's own Chromium patches and generated API files first.
        # Otherwise compilation would legitimately change the baseline after
        # our source ledger was recorded (or collide with our native hooks).
        run([sys.executable, "-u", repositories["cef"] / "tools/gclient_hook.py"],
            cwd=repositories["cef"], env=env)
    records = apply_series(repositories, PATCHES, lock)
    if destination.exists():
        validate(destination, records, build_identity(lock))
        probe(destination)
        print(f"Existing validated custom engine: {destination}")
        return
    run(arguments(work, lock) + ["--no-update", "--force-build", "--force-distrib",
                               "--minimal-distrib-only", "--no-distrib-docs",
                               "--no-distrib-symbols"], cwd=work, env=env)
    # Re-check source provenance after the build, before declaring success.
    apply_series(repositories, PATCHES, lock)
    name = f"cef_binary_{lock['cef_version']}_macosarm64_minimal"
    distribution = repositories["cef"] / "binary_distrib" / name
    archive = Path(str(distribution) + ".tar.bz2")
    if not archive.is_file():
        raise ValueError(f"CEF did not produce the expected archive: {archive}")
    stage(distribution, destination)
    seal_distribution(destination, records, lock, archive)
    probe(destination)
    print(f"Validated custom engine: {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "prepare", "build", "validate"))
    parser.add_argument("--work-dir", type=Path, default=ROOT / "target/native-cef")
    parser.add_argument("--output", type=Path, default=ROOT / "target/native-cef-artifact")
    args = parser.parse_args()
    work, destination = args.work_dir.resolve(), args.output.resolve()
    if any(character.isspace() for character in str(work)):
        raise ValueError("CEF automate requires a build path without whitespace")
    lock = load_lock()
    env = environment(work, lock)
    if args.command == "validate":
        print(validate(destination, lock["patches"], build_identity(lock)))
        probe(destination)
        return
    doctor(env)
    if args.command == "prepare":
        prepare(work, lock, env)
    elif args.command == "build":
        build(work, destination, lock, env)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
