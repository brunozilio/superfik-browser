# Superfik native CEF

This directory owns the engine source lock and ordered native patch series.
The target is macOS Apple Silicon. It does not replace `welding`: engine changes
and Rust/CEF integration changes have separate version histories.

## Current status

The published `cef-154.0.34-superfik.1` engine supports native CPU/memory
profiles, including negotiated memory client hints. Its runtime isolation was
validated in pages, frames and dedicated workers, with defaults/private
contexts preserved.

The next candidate adds per-context native GPU identity, seeded canvas/audio
readbacks, local-font restrictions and WebRTC construction policy. App-side
CEF integration supplies screen metrics, fixed HTTP(S) proxies, scoped proxy
authentication and the Settings profile editor. No JavaScript API shims are
used.

The candidate passed isolated acceptance in pages, frames and workers,
including WebGL2 pixel-pack buffers and floating-point reads, repeated process
launches, default/private contexts, legacy real-value restoration and native
clicks at DPR 1/2. Nine proxy scenarios cover HTTP/TLS proxies, HTTP/TLS origins,
CONNECT, worker requests, invalid credentials, unavailable proxies, certificate
rejection and no direct origin/UDP fallback.

These are laboratory controls, not GPU/audio-device emulation or a guarantee
of universal website compatibility. See [native profile protocol](PROFILE_PROTOCOL.md).

## Hardware experiment configuration

Settings → Browser manages the new profile library. For legacy CPU/memory-only
experiments, place `superfik-identity.json` in the existing
conversation browser profile directory (`browser/profile-<conversation-id>`
under Superfik's application data directory):

```json
{
  "schema": 1,
  "enabled": true,
  "hardware_concurrency": 4,
  "device_memory": 8
}
```

Unspecified fields retain platform behavior. CPU accepts 1–1024; memory accepts
0.25, 0.5, 1, 2, 4 or 8 GiB. Missing files or `enabled: false` preserve actual
hardware values. Unknown fields, unsupported schemas and invalid values fail
before page creation. Private browser contexts do not read persistent identity
files. Existing profiles/cookies are preserved.

For this initial renderer-launch transport, **restart Superfik after changing
an identity**. The host refuses a changed identity within the same process, so
existing service workers or renderers cannot silently retain an old value.
The Rust integration applies preferences before the first browser is created;
stock CEF rejects an enabled experiment instead of ignoring it. No GPU or
hardware-emulation capabilities are added by these overrides.
Native profile initialization resets persisted experimental preferences before
the host applies its configuration, including explicit defaults for private
contexts instead of inheriting a parent profile's experiment.

## Build

Run from the repository root with full Xcode installed:

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -downloadComponent MetalToolchain
python3 scripts/build_cef.py doctor
python3 scripts/build_cef.py prepare
python3 scripts/build_cef.py build
python3 scripts/cef_artifact.py target/native-cef-artifact --probe
```

Preparation downloads Chromium and its dependencies into `target/native-cef`.
It uses the upstream CEF automation script from the pinned CEF checkout and a
pinned depot_tools checkout, with Chromium history downloads disabled. Chromium
comes from its official GitHub mirror; its resolved commit is checked against
the lock independently of the version tag. Building
Chromium requires substantial disk, network and compilation time. No remote
execution service is used. Xcode is selected in the child environment only.
Use a versioned Xcode installation via `DEVELOPER_DIR` to keep the SDK stable
between incremental builds. Changing Xcode/SDK versions can invalidate caches;
the matching Metal component must be installed for that Xcode version.
The build fetches the pinned Chromium and V8 profiles and uses official-release
PGO optimization.

`--work-dir` and `--output` override the two directories. Do not use whitespace
in the work directory. The pipeline does not clean or reset source modifications.
After patch application, use `build` to resume. If the patch ledger reports
divergence or interruption, inspect that checkout and use a separate work
directory rather than discarding its changes.

## Patch and artifact provenance

`engine.lock.json` pins CEF, Chromium, depot_tools, GN arguments and the ordered
patch checksums. Patches specify `cef` or `chromium` as their source repository.
Update a checksum deliberately when reviewing a patch change. An existing
patched checkout rejects changed/reordered entries. A strictly appended series
can reuse the build cache only after verifying the previous source ledger.

The staging step produces the flattened distribution layout consumed by
`cef-dll-sys`, including its `archive.json` compatibility metadata. It hashes all
files, rejects escaping symlinks and records build provenance in
`superfik-engine.json`. Validation occurs before codesigning modifies bytes.

Applications pass the validated distribution directory as `CEF_PATH` to their
own CEF packaging step. Application-specific packaging is outside this repo.

The native marker uses the private `cef_version_info(0x535546)` entry, returning
`1`; ordinary version fields and the public CEF ABI are unchanged. `--probe`
loads the framework and checks that marker without initializing CEF or opening
a browser profile. Application packaging should require this probe.

A checksum manifest and marker identify an artifact; neither is a signature or
proof of experimental behavior. Only consume artifacts from a trusted builder.

## Verification

```sh
python3 -m unittest discover -s scripts -p 'test_cef_*.py'
```

Tests use temporary distributions and local Git repositories. Successful tests
or `git apply --check` do not replace compiling and running the real engine.
