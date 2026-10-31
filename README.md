# Superfik Browser

Experimental CEF/Chromium patches and build tooling for Superfik.

The engine is built locally on macOS Apple Silicon and distributed as versioned
GitHub Release assets. The application CI downloads a pinned engine instead of
rebuilding Chromium. Public GitHub Actions runs the small Python test suite;
it does not compile Chromium on the standard hosted macOS runner.

## Status

The initial engine compiled locally and passed artifact integrity and native
marker checks. No binary release is published yet. The patch series adds an engine marker and
opt-in CPU/memory overrides per browser context, including device-memory
client hints. Runtime isolation and compatibility testing are still required.
GPU, canvas, audio and other fingerprint overrides are not implemented.

Integration acceptance confirmed distinct CPU/memory values in pages, iframes
and dedicated workers, and preserved defaults in unmodified/private contexts.
It also exposed a renderer-side device-memory HTTP hint inconsistency. The
current patch revision moves that override into Blink's shared memory helper;
its rebuilt artifact and complete acceptance test are still pending.

## Build and validate locally

Full Xcode, its Metal component, and substantial free disk space are required.
The CEF build documentation recommends at least 16 GB RAM and 200 GB free disk.
See [CEF build setup](https://github.com/chromiumembedded/cef/blob/master/docs/automated_build_setup.md).

```sh
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer xcodebuild -downloadComponent MetalToolchain
python3 scripts/build_cef.py doctor
python3 scripts/build_cef.py prepare
python3 scripts/build_cef.py build
python3 scripts/build_cef.py validate
```

The source revisions and patch hashes are pinned in
[`native/cef/engine.lock.json`](native/cef/engine.lock.json).
See [engine details](native/cef/README.md) for configuration and resume rules.

## Publish a candidate

After the engine build succeeds, create a local release package and a draft:

```sh
python3 scripts/publish_engine.py target/native-cef-artifact \
  --tag cef-154.0.34-superfik.1
```

The publisher verifies the native marker, manifest, patch hashes and build
configuration. It creates a draft release with the archive, its SHA-256 and
the engine manifest. Review and test the candidate before publishing the draft.
No signing credentials, user profiles, cookies or application data belong here.

## Tests

```sh
python3 -m unittest discover -s scripts -p 'test_cef_*.py'
```

Build scripts are MIT licensed. Native patches modify BSD-licensed upstream
code; see [third-party notices](THIRD_PARTY_NOTICES.md).
