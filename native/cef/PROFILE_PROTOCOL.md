# Native laboratory profile protocol

All settings are opt-in and must be applied before the request context creates
renderers. A renderer belongs to one BrowserContext and receives only that
context's immutable configuration. Changing a live profile requires restarting
the application so workers/renderers cannot retain a different identity.

## Preferences and transport

- `superfik.identity.enabled`: boolean, false initially.
- `superfik.identity.hardware_concurrency`: integer, zero retains actual value.
- `superfik.identity.device_memory`: double, zero retains actual value.
- `superfik.identity.configuration`: JSON string, empty initially. The renderer
  receives this as the Base64 `superfik-profile` switch only when enabled.

The native initialization resets these preferences, including private contexts.
The app validates profile values before setting them and rejects unsupported
engines instead of silently ignoring experimental fields. The engine ABI marker
remains `cef_version_info(0x535546) == 1`; the extended preference identifies the
new protocol without changing the public CEF ABI.

```json
{
  "enabled": true,
  "seed": 1001,
  "gpu": {"vendor": "Laboratory", "renderer": "Profile A", "architecture": "", "device": "", "description": ""},
  "canvas": true,
  "audio": true,
  "fonts": ["Times New Roman"],
  "webrtc": "disabled"
}
```

The profile's seed is generated once and saved; it does not rotate per site or
launch. Missing fields preserve platform behavior. CPU/memory continue through
their dedicated preferences and share memory values with HTTP hints.

## Surfaces

GPU configuration changes WebGL/WebGPU identification strings. Actual supported
features, device execution and limits still come from the real adapter.

Canvas readbacks use canonical 8-bit RGB and seed-derived low bits without
modifying displayed backing stores. Coverage includes Canvas2D, image exports,
OffscreenCanvas, WebGL normalized/floating-point RGBA reads and WebGL2 pixel-pack
buffers. Float outputs are converted back to their requested representation;
canonicalization can reduce precision for HDR workflows. The transformation is
idempotent, so cropped reads/exports and pixel-pack retrieval agree.

Audio applies a stable low-mantissa transformation to offline results and
analyser readbacks. Silent/non-finite values are preserved. No microphone or
audio device is emulated.

The font list restricts native local-font matching and FontAccess enumeration.
System/last-resort/emoji fallback remains usable. Downloaded web fonts retain
their behavior. WebRTC can retain system behavior, disable direct UDP through
Chromium's `webrtc.ip_handling_policy`, or reject peer connection creation.

## Client integration

The application supplies screen rectangles, color depth and device scale through
CEF's native RenderHandler. Its offscreen rendering and physical-to-DIP input
use the same scale. Screen fields do not require JavaScript replacements.

Apply proxy preferences per RequestContext, using `fixed_servers`, an HTTP(S)
server URI and `bypass_list: "<-loopback>"`. Do not include a DIRECT alternative.
Use `disable-chrome-login-prompt` so CEF routes authentication to the client's
GetAuthCredentials callback. Supply credentials only for the configured proxy
host/port and never for server authentication. Store passwords in the OS
credential store; exclude them and proxy settings from renderer JSON/switches.
With a proxy, disable non-proxied WebRTC UDP.

The app's isolated fixture validates real/default, private and distinct profiles,
page/frame/worker agreement, restarts, memory hints and clicks at DPR 1/2. Its
loopback HTTP/TLS fixture verifies authentication, CONNECT, workers and failure
without direct fallback. Debug TLS tests pin only their generated certificate's
SPKI; production certificate policy remains unchanged.
