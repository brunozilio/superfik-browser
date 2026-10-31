"""Pinned CEF pipeline primitives. Never reset or clean a source checkout."""

import hashlib
import json
from pathlib import Path
import subprocess

from cef_artifact import CEF_COMMIT, CEF_VERSION, TARGET, build_identity, digest, validate

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "native/cef/engine.lock.json"
PATCHES = ROOT / "native/cef/patches"


def run(arguments, cwd=None, env=None):
    subprocess.run([str(value) for value in arguments], cwd=cwd, env=env, check=True)


def output(arguments, cwd):
    return subprocess.check_output(arguments, cwd=cwd, text=True).strip()


def load_lock():
    data = json.loads(LOCK.read_text())
    if (data["schema"], data["cef_commit"], data["cef_version"], data["target"]) != (
        1, CEF_COMMIT, CEF_VERSION, TARGET
    ):
        raise ValueError("engine lock disagrees with the artifact validator")
    return data


def patch_records(patches, lock):
    records = []
    names = set()
    for item in lock["patches"]:
        name = item["name"]
        path = (patches / name).resolve(strict=True)
        if not path.is_relative_to(patches.resolve()) or path.suffix != ".patch":
            raise ValueError("patch path escapes patch directory or is not a patch")
        if name in names or item["repository"] not in ("cef", "chromium"):
            raise ValueError("duplicate patch or unknown source repository")
        names.add(name)
        checksum = digest(path)
        if checksum != item.get("sha256"):
            raise ValueError(f"patch checksum mismatch: {name}")
        records.append(dict(item, sha256=checksum))
    return records


def source_state(directory, patch_paths):
    # CEF generates untracked C API files during compilation. Hash tracked
    # edits plus every reviewed patch target, including newly added sources,
    # rather than accidentally treating generated files as source divergence.
    result = hashlib.sha256()
    result.update(subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=directory))
    for name in sorted(patch_paths):
        path = directory / name
        result.update(name.encode() + b"\0")
        if path.is_symlink():
            result.update(str(path.readlink()).encode())
        elif path.is_file():
            result.update(digest(path).encode())
    return result.hexdigest()


def apply_series(repositories, patches, lock):
    records = patch_records(patches, lock)
    targets = {name: set() for name in repositories}
    for record in records:
        stats = output(["git", "apply", "--numstat", str((patches / record["name"]).resolve())],
                       repositories[record["repository"]])
        for line in stats.splitlines():
            name = line.split("\t", 2)[-1]
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or '"' in name or " => " in name:
                raise ValueError("patch target is not a supported repository-relative path")
            targets[record["repository"]].add(name)
    # Keep the ledger outside both Git trees; otherwise its own bytes would
    # change the recorded source state on every resume.
    state_file = repositories.get("chromium", repositories["cef"]).parent / "superfik-patches.json"
    heads = {name: output(["git", "rev-parse", "HEAD"], path)
             for name, path in repositories.items()}
    if state_file.exists():
        state = json.loads(state_file.read_text())
        current = {name: source_state(path, targets[name]) for name, path in repositories.items()}
        if state != {"patches": records, "heads": heads, "sources": current}:
            raise ValueError("patched checkout diverged; preserve it and use a new build directory")
        return records
    # A failed application intentionally leaves no success ledger. Do not
    # retry over that checkout: report it so the caller can inspect the edits.
    progress = state_file.with_suffix(".in-progress")
    if progress.exists():
        raise ValueError("patch application was interrupted; inspect checkout before retrying")
    progress.write_text(json.dumps({"patches": records, "heads": heads}, indent=2))
    for item in records:
        repository = repositories[item["repository"]]
        patch = (patches / item["name"]).resolve()
        run(["git", "apply", "--check", patch], cwd=repository)
        run(["git", "apply", patch], cwd=repository)
    state = {"patches": records, "heads": heads,
             "sources": {name: source_state(path, targets[name]) for name, path in repositories.items()}}
    state_file.write_text(json.dumps(state, indent=2) + "\n")
    progress.unlink()
    return records


def seal_distribution(directory, records, lock, archive):
    """Create a manifest only after a nonempty, verified patch series built."""
    if not records:
        raise ValueError("refusing to label an unpatched CEF as custom")
    manifest = directory / "superfik-engine.json"
    if manifest.exists():
        raise ValueError("distribution already sealed; validate it instead")
    metadata = directory / "archive.json"
    if not metadata.exists():
        archive_hash = hashlib.sha1()
        with archive.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                archive_hash.update(chunk)
        metadata.write_text(json.dumps({
            "name": archive.name,
            "type": "minimal", "sha1": archive_hash.hexdigest(),
        }) + "\n")
    files = {}
    links = {}
    for path in directory.rglob("*"):
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("distribution contains an escaping symlink")
        if path.is_symlink():
            links[path.relative_to(directory).as_posix()] = path.readlink().as_posix()
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = digest(path)
    data = {"schema": 1, "cef_commit": CEF_COMMIT, "target": TARGET,
            "patches": records, "files": files, "symlinks": links,
            "build": build_identity(lock)}
    manifest.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    try:
        return validate(directory, records, build_identity(lock))
    except Exception:
        manifest.unlink()
        raise
