# Computer Use (Linux): architecture decision record

Status: **Phase 0 complete. Phase 1 (observation tools) complete. Phase 2
(actions + kernel input + Wayland targeting) implemented and dogfooded on
GNOME Wayland. Phase 3 now has on-demand capture, region cropping, ref-bound
annotation and local OCR boxes; the stale-ref/modal/multi-monitor adversarial
suite is in place. Phase 5 includes the popup, region overlay, global hotkeys,
settings and Linux packaging, the redesigned any-app popup, the optional
click-through ghost cursor, and the nested Xephyr/openbox X11 gate. Computer
use is enabled by default and targets any desktop app. The 20-task dogfood
benchmark passes its acceptance target: 20/20 (100%), zero screenshots.**

A 2026-11-09 reliability pass addressed the gap between that benchmark and
real browser use: the default observation depth is now 40 (500 nodes), large
trees are emitted content-first, `find` returns partial matches instead of
discarding them, mutating actions report a post-action diff, app aliases
resolve through process/flatpak/title evidence, Chromium DevTools endpoints
are auto-discovered, and the resolver refuses a launcher script that shares the
sidecar's name. Wayland pointer delivery now uses Mutter RemoteDesktop when
coordinates are proven, Unicode typing uses clipboard paste with restore, and
a persistent xdg-desktop-portal ScreenCast capture path supplements the
per-call Screenshot portal. No additional browser runtime is required.

This document records the decisions behind Palimind's computer-use capability,
the threat model, the licence obligations of the vendored engine, and the
measured facts that shaped the implementation. The source plan is
`~/.opencode/plan/computer-use-kernel-level.md`.

## 1. Scope

Palimind can see and operate desktop applications on Linux:

* **Observe** through the OS accessibility tree (AT-SPI2 over D-Bus).
* **Act semantically** first (`Action.DoAction`, `Text`, `Value`, `Selection`).
* **Act physically** only as a fallback: XTEST on X11, Mutter RemoteDesktop on
  Wayland, or the opt-in `/dev/uinput` kernel backend.
* **Capture on demand** only, and only locally.

Out of scope for v1: Windows, macOS, a custom kernel driver, cloud vision,
secure system dialogs, password managers, lock screens and elevated windows.

## 2. What "kernel level" means

There is no kernel API that says where a button is. Discovery is an
observation problem solved in user space. "Kernel level" is meaningful only
for **input delivery**:

| Layer | Mechanism | Privilege |
|---|---|---|
| Observe | AT-SPI2 over D-Bus | normal user |
| Act semantically | AT-SPI actions / text / value / selection | normal user |
| Act physically (X11) | XTEST | normal user |
| Act physically (Wayland) | Mutter RemoteDesktop portal | user consent |
| Kernel input (opt-in) | `/dev/uinput` virtual HID device | user in `input` group |
| Vision fallback | display capture + local OCR/vision | normal user + portal consent |

We do **not** ship a kernel module or a setuid helper. `/dev/uinput` is the
kernel path; the kernel already provides it.

## 3. Native base: vendored agent-desktop

We vendor `crates/core` and `crates/linux` from agent-desktop v1.1.0
(Apache-2.0) under `packages/desktop-native/vendor/agent-desktop/`.

Why:

* The hard correctness work is already implemented and measured: strict
  snapshot-qualified refs and re-resolution, capture proofs, tri-state
  evidence, actionability gates, delivery dispositions, interaction leases,
  secure fields, protected processes, toolkit quirks, settle waits.
* Core is platform-neutral (`ObservationOps`, `ActionOps`, `InputOps`,
  `SystemOps`); only the Linux implementation is built here.
* Reimplementing AT-SPI edge cases clean-room would take months and would
  start behind.

What we add on top (the Palimind delta):

* `palimind-desktop`: a thin Linux binary with a CLI and a stdio JSON-RPC
  daemon, a Palimind envelope, app policy, audit, rate limiting and stop.
* The kernel input backend (`/dev/uinput`) in `palimind-desktop/src/uinput.rs`.
* Wayland pointer-targeting policy: semantic first; a physical pointer needs a
  proven global coordinate source, otherwise it is refused.
* at-spi2-core 2.44 compatibility fixes in the Linux crate (see §5).

Licence obligations are in `packages/desktop-native/NOTICE`; every modified
upstream file carries a `// Palimind:` marker; the full delta is
`packages/desktop-native/patches/0001-atspi44-compat.patch`.

## 4. Architecture

```
React UI (Settings / popup / timeline)
        │ Tauri IPC / REST
Tauri shell
        │ spawns
Python backend
  agents/tools/desktop/  → tool schemas + policy + formatting
  /api/desktop/*         → status, session, stop, audit, shots
        │ stdio JSON-RPC (same user)
palimind-desktop serve
  ├─ policy + audit + rate limit + stop
  ├─ AT-SPI2 observation and semantic actions (vendored core/linux)
  ├─ input: XTEST / Mutter RemoteDesktop / uinput (opt-in)
  └─ capture: X11 or portal, on demand
```

The daemon is a child of the Python backend, so it inherits the graphical
session environment. No port, token or Tauri bridge is involved.

Transport:

1. Preferred: Python spawns `palimind-desktop serve` and speaks
   newline-delimited JSON-RPC over stdin/stdout.
2. Optional: a 0600 Unix socket under `$XDG_RUNTIME_DIR/palimind/`.
3. Fallback: per-call `palimind-desktop <command>` with the same envelope.

The binary is located via `PALIMIND_DESKTOP_BIN`, the bundled app resource
path, or `PATH`.

## 5. Measured at-spi2-core 2.44 findings (2026-11-05)

Environment: GNOME Wayland, at-spi2-core 2.44.0, GTK3 zenity and GNOME
Calculator. These measurements changed the fork and are the reason the local
delta exists.

1. **`RegisterEvent` signature.** The vendored adapter called
   `org.a11y.atspi.Registry.RegisterEvent` with `(s, as, s)`. The installed
   registry declares `RegisterEvent(s)` and logs `invalid signature 'sass'`.
   The adapter now calls the one-argument form.
2. **`Action.GetActions` aborts applications.** Several widgets advertise the
   Action interface while their ATK user-data is not an `AtkAction`. Calling
   `GetActions` makes the application abort while serializing the `a(sss)`
   reply:
   * GTK3 zenity calendar: role `panel` and image-backed push buttons.
   * GNOME Calculator: the unit combo, its menu items, and even digit buttons.
   The error is `impl_GetActions: assertion 'ATK_IS_ACTION (user_data)'
   failed` followed by `dbus: ... expected 'a(sss)'`.
3. **`Action.GetName(i)` is safe.** The same nodes answer `GetName(0)`
   (`click`, `press`) without aborting. The fork therefore probes
   `GetName(0..8)` and never calls `GetActions`. This preserves real action
   names and capability detection.
4. **Stale window entries.** The AT-SPI registry keeps windows from dead
   processes. `palimind-desktop` filters `list-windows` by live PID and passes
   the resolved window id to snapshot/find so a dead twin cannot produce
   `AMBIGUOUS_TARGET`.
5. **Wayland bounds are window-local.** A maximized calculator reports
   `bounds: [0,0,412,541]` on Wayland. The envelope marks `bounds_space` as
   `window` on Wayland and `screen` on X11; physical pointer actions require a
   proven global coordinate source.

## 6. Data model and contracts

### Snapshot

```json
{
  "snapshot_id": "s3f9k2",
  "app": {"name": "gnome-calculator", "pid": 8255, "desktop_id": null},
  "window": {"id": "w-...", "title": "Calculator", "bounds": {...}},
  "complete": true,
  "truncated": false,
  "node_count": 49,
  "bounds_space": "window",
  "nodes": [
    {
      "ref": "@s3f9k2:e7",
      "role": "button",
      "name": "7",
      "value": null,
      "description": null,
      "native_id": null,
      "bounds": [120, 300, 60, 48],
      "bounds_space": "window",
      "states": [],
      "actions": ["Click", "SetFocus"],
      "redacted": false
    }
  ]
}
```

Rules:

* A ref is snapshot-qualified (`@<snapshot_id>:eN`); bare `@eN` is rejected.
* Offscreen and defunct subtrees are omitted by default (the engine marks
  them); `full=true` is the explicit escape hatch that also returns the raw
  tree.
* Secure fields are redacted (`name: "[redacted]"`, no value/description, and
  descendants inherit the redaction).
* The result carries a provenance marker: accessibility text is application
  data, never instructions.
* Observation defaults are depth 40 and 500 nodes, with a 20 s snapshot
  deadline (15 s for `find`). Chromium web-content trees nest page content
  deeper than the old depth-12 cap, so the cap returned browser chrome only.
  Deep trees are emitted content-first when truncated: page links, text and
  controls precede window chrome, and hidden/zero-size nodes move to the end.
  The formatter drops unnamed structural wrappers, de-duplicates unnamed
  repeats, and states the truncation reason with a concrete next step.
* When the authoritative locator cannot finish on a large tree, `find`
  returns the matches it can prove from a bounded snapshot search, marked
  `partial: true` with `total_matches`. It no longer discards 29 observed
  matches because the traversal ran out of budget.
* `desktop_act` re-observes the same app/window after a mutating action and
  reports `new`, `removed` and `changed` nodes. The result is advisory: an
  accessibility diff cannot see canvas or web-content effects, so the tool
  says so and asks the agent to re-observe before retrying.
* App names are resolved through an alias pass: exact AT-SPI name first, then
  process name, executable, flatpak cgroup, and finally a unique window title.
  This is why a Flatpak launcher name such as `zen` now reaches the window even
  when AT-SPI exposes it as `xdg-dbus-proxy`. Policy is checked on the
  requested name before resolution, so an alias cannot bypass a protected app.

### Errors

Stable codes: `INVALID_ARGS`, `PERM_DENIED`, `PLATFORM_NOT_SUPPORTED`,
`POLICY_DENIED`, `APP_NOT_FOUND`, `WINDOW_NOT_FOUND`, `STALE_REF`,
`AMBIGUOUS_TARGET`, `ACTION_NOT_SUPPORTED`, `ACTION_FAILED`, `TIMEOUT`,
`BUSY`, `INTERNAL`.

Each error carries `code`, `message`, optional `hint`/`details`, and a
`disposition` with `delivery` and `retry`. Only `not_delivered` actions are
safe to retry.

### CLI / daemon methods

`status`, `apps`, `snapshot`, `find`, `wait`, `act`, `screenshot`, `launch`,
`serve`, `stop`, `resume`, `audit`.

`act` actions: `click`, `double_click`, `right_click`, `hover`, `focus`,
`type`, `set_value`, `clear`, `select`, `toggle`, `check`, `uncheck`, `scroll`,
`scroll_to`, `drag`, `press_key`, `type_text`, `launch`, `close`,
`focus_window`.

## 7. Security model

Layered gates:

1. `PALIMIND_DESKTOP_ENABLE` master switch, **on by default** (`=0` turns it
   off), enforced in the native binary for every method except `status` (the
   onboarding probe).
2. Per-agent `desktop_access` (observe) and `desktop_control` (mutate).
3. Tool tiers/approval: observe tier 1, act/launch/screenshot tier 2 with
   approval.
4. Native policy: **any app is allowed by default**; a non-empty allowlist
   narrows that, and the blocklist plus the hard protected-process set always
   win. A per-agent `desktop_allowed_apps` list becomes the effective native
   allowlist for that agent's daemon.
5. Session grant: "allow for this run" with a visible Stop.

Hard rules enforced in the native binary:

* Protected processes are refused even when allowlisted: GNOME Shell,
  plasmashell, kwin/mutter, gnome-settings-daemon, session managers,
  polkit agents, keyrings, lock screens, and Palimind's own windows.
* Secure/password fields are redacted; their subtree never returns text.
* Destructive-sounding labels require an explicit confirmation flag even in
  Act mode. The native layer reads the stored ref's captured name, description
  and value, so a bare ref such as `@s1:e7` cannot hide a "Delete" label.
* One machine-wide interaction lease; action rate limit (default 30/min).
* Stop releases held keys/buttons, ends a RemoteDesktop session, and disables
  the daemon session until resumed.
* Audit log at `~/.palimind/desktop/audit.jsonl` (0600). Typed text is never
  logged: only a salted digest and length.
* Screenshots are opt-in, stored 0700 under `~/.palimind/desktop/artifacts`,
  pruned after 24h by default, never uploaded.

Prompt injection: observations are wrapped in a typed envelope with
`content_trust: untrusted_data`; UI text is never put in the system prompt;
the app allowlist is applied before observation; destructive actions need
confirmation.

## 8. Kernel input (`/dev/uinput`)

`palimind-desktop/src/uinput.rs` creates a virtual keyboard and absolute
pointer named `Palimind Virtual Input` (BUS_VIRTUAL). It keeps the device open
for the command, emits `EV_SYN` after batches, and releases held keys/buttons
on drop or panic.

* Requires the `uinput` module and `/dev/uinput` permission. Install the udev
  rule with `sudo scripts/install-uinput-udev.sh`; the user must be in the
  `input` group and log back in. Palimind never ships a setuid helper.
* Absolute pointer coordinates are mapped from display pixels into
  `0..=65535` device units against the primary display.
* `status` reports `available-but-not-permitted` when the device exists but
  cannot be opened.

### Wayland input without `/dev/uinput`

`/dev/uinput` is no longer required for Wayland pointer or Unicode typing:

* **Pointer.** `agent_desktop_linux::send_absolute_pointer_click` uses the
  existing Mutter RemoteDesktop session to move and click at proven global
  coordinates. `PALIMIND_DESKTOP_INPUT_BACKEND=auto` tries Mutter first and
  falls back to uinput if the compositor refuses; `mutter` makes it the only
  route, and `uinput` keeps the old behaviour. The `TARGET` is still refused
  unless the coordinate source is global (see §9).
* **Unicode typing.** `agent_desktop_linux::type_text_via_clipboard` sets the
  clipboard (`wl-copy` when installed, otherwise `xclip` through the XWayland
  bridge), sends Ctrl+V through the compositor, waits for the focused
  application, and restores the previous text clipboard. This replaces the
  US-keymap refusal for non-ASCII text. If neither clipboard tool exists the
  command fails closed with an install hint; it never silently drops text.

`scripts/install-uinput-udev.sh` is still the right choice for global keys on
X11 or when the operator prefers kernel delivery.

## 9. Wayland pointer targeting

A physical pointer action on Wayland is allowed only when the coordinate
source is global:

* explicit user coordinates,
* a full-display screenshot + local OCR/vision pass,
* compositor/ScreenCast geometry,
* known geometry from a maximized/fullscreen window.

AT-SPI bounds are window-local on Wayland and are refused
(`PLATFORM_NOT_SUPPORTED`) before any event is emitted. When the source is
proven, delivery uses Mutter RemoteDesktop absolute motion; `/dev/uinput` is
not required. On X11, screen coordinates are available and XTEST/uinput work
directly. Semantic actions need no coordinates and are always preferred.

### Persistent Wayland capture (ScreenCast)

`palimind-desktop/src/screencast.rs` is the Wayland vision fallback. It uses
the xdg-desktop-portal `ScreenCast` interface rather than per-call
`Screenshot`:

1. `CreateSession` → `SelectSources` (`types=1` monitor, `multiple=false`,
   `persist_mode=2`) → `Start`.
2. The portal returns a PipeWire node and a `restore_token`; the token is
   written to `~/.palimind/desktop/screencast-token` (0600). Later sessions
   pass it back, so the source dialog appears only once.
3. `OpenPipeWireRemote` returns the PipeWire file descriptor; Palimind clears
   `FD_CLOEXEC` and lets `gst-launch-1.0 pipewiresrc fd=… path=…` extract a
   small burst of frames to a PNG. If the fd route is unavailable it retries
   with `path=…` alone.
4. The PNG goes through the normal artifact directory and 24 h retention. No
   recording is kept; the pipeline stops after `num-buffers=30`.

When the `Screenshot` portal refuses (denied) or a single window is requested
on Wayland, `screenshot` falls back to this path and returns
`capture=screencast`, `scope=screen`. The tool layer labels the image as the
whole monitor and skips window-relative annotation. `desktop_screenshot` OCR
boxes are therefore screen coordinates.

Diagnostics:

```bash
palimind-desktop screencast --out /tmp/shot.png
# status.screencast_token reports whether the restore token exists
```

The first capture requires a person to approve the portal's source dialog.
That is the portal's consent boundary; Palimind does not bypass it.

## 10. Verification

Host test set (all green):

```bash
cd packages/desktop-native
cargo test -p agent-desktop-core -p agent-desktop-linux -p palimind-desktop
cargo clippy -p agent-desktop-core -p agent-desktop-linux -p palimind-desktop \
  --all-targets -- -D warnings
```

Calculator dogfood (Wayland, 2026-11-05):

```
snapshot gnome-calculator            → 49 nodes, refs for 7 + 8 =
act click @...:e204 (7)              → delivered_unverified
act click @...:e190 (+)              → delivered_unverified
act click @...:e203 (8)              → delivered_unverified
act click @...:e182 (=)              → delivered_unverified
snapshot gnome-calculator            → statictext "15", "7+8"
```

Zero screenshots. That is the plan's Phase 2 acceptance case.

Python tool layer, same loop through the stdio daemon:

```
DesktopClient().act(action="launch", app="gnome-calculator")
desktop snapshot (interactive_only=false) → 57 nodes, refs for 7 + 8 =
act click ×4                             → delivered_unverified
final snapshot                           → statictext "15", "7+8"
```

Kernel input fails closed before any event when the udev rule is absent:

```
act press-key --key ctrl+s --kernel
→ PERM_DENIED: Cannot open /dev/uinput ... install scripts/install-uinput-udev.sh
```

Frontend surfaces render in the SSR smoke test:

```
PASS computer use popup
PASS computer use region overlay
SMOKE OK
```

Region cropping is unit-tested with a real PNG (20×20 crop from a 100×100
capture), annotation boxes are verified against snapshot bounds within one
pixel (screen, scaled, cropped and window-relative), OCR boxes are unit-tested
with a fake reader and labelled `ocr:<n>`, and the packaged artefacts contain
the sidecar:

Real local OCR (easyocr, no network) on a generated 320×100 image:

```
annotation.ocr_boxes("/tmp/ocr-probe.png")
→ [{'ref': 'ocr:0', 'kind': 'ocr', 'text': 'SAVE', 'confidence': 0.994,
    'image_box': [18, 22, 130, 50], 'stable': False}]
```

Phase 6 20-task dogfood benchmark (`make desktop-dogfood`):

```
19/20 tasks passed (95%), screenshots=0, snapshots=49
ACCEPTANCE PASS
```

Categories: calculator 4/4, editor/text entry 4/4, file manager 4/4,
settings 4/4, browser 3/4. Editor coverage observes gedit's document field and
uses a zenity entry for typing/set_value/clear because gedit exposes two
unnamed text fields with an ambiguous upstream ref. The one failure is the semantic click on a Chromium
web-content button (`AMBIGUOUS_TARGET`); Chromium's web content needs the CDP
route the reference project uses, while window/menu/page observation works.
The benchmark starts its own app processes, restarts the calculator and
settings per task for deterministic state, and counts screenshots by wrapping
the client method (49 snapshots, 0 screenshots). The raw report is checked in
at `benchmarks/desktop-dogfood-2026-11-05.json`.

X11 release gate — run on a nested Xephyr display with openbox via
`make desktop-x11-gate` (or `scripts/run-x11-gate.sh`):

```
status: passed
status_x11                    ok  (XDG_SESSION_TYPE=x11, screen_coordinates_available)
snapshot_refs_and_bounds      ok  (49 nodes, 30 refs)
semantic_calculator_7_plus_8  ok  (display 15)
x11_screenshot                ok  (1600x1200 local PNG)
```

Report: `benchmarks/x11-validation-2026-11-05.json`. A real X11 login works
with `make desktop-x11-check`; the nested runner needs `Xephyr` and `openbox`
(or `OPENBOX_BIN`), and does not require root.

Phase 6 adversarial suite (`tests/test_desktop_adversarial.py`, live tests run
with the built binary):

```
10 passed
```

It covers prompt-injection framing (the untrusted-data note precedes every
application string, including the window title), secure-field redaction,
stale-ref non-retry, destructive-action refusal, negative-origin/HiDPI
multi-monitor mapping, OCR boxes staying `stable: false`, a live zenity modal,
protected `gnome-shell` refusal under `ALLOW_ALL`, a target killed mid-run
(old refs no longer actionable, never a safe retry), and display geometry/scale.

Screenshot policy was exercised natively:

```
PALIMIND_DESKTOP_SCREENSHOT=off
→ POLICY_DENIED: Screenshots are disabled by PALIMIND_DESKTOP_SCREENSHOT=off
PALIMIND_DESKTOP_SCREENSHOT=on_demand
→ PERM_DENIED from the portal (policy passed; a person must allow capture)
```

```
dpkg-deb -c deb/Palimind_0.1.0_amd64.deb | grep palimind-desktop
→ ./usr/bin/palimind-desktop
AppImage --appimage-extract → squashfs-root/usr/bin/palimind-desktop
```

Wayland targeting refuses unproven coordinates before dispatch:

```
act click --x 100 --y 100 --coords-source atspi --kernel
→ PLATFORM_NOT_SUPPORTED: ... will not guess a window-local AT-SPI coordinate
```

Measured snapshot latency after offscreen-subtree pruning and removal of a
redundant preflight window lookup (warm daemon, release build, 49 visible
calculator nodes):

```
snapshot(app=..., interactive_only=false)        p50 97 ms  · p95 100 ms
snapshot(app=..., window_id=..., interactive...)  p50 80 ms  · p95 85 ms
snapshot(window_id=only)                          p50 147 ms · p95 155 ms
```

All three paths meet the plan's 250 ms target on the release build (the debug
build was ~177 ms for the app path). Before pruning the same tree took
p95 ≈ 476 ms; the walker now stops descending below nodes whose AT-SPI
`SHOWING` bit is clear (closed menus/popups), which removed roughly 90% of the
visited nodes. Window-id-only still pays one `list-windows` round trip to learn
the app name for policy; callers that already know the app should pass it.
`PALIMIND_DESKTOP_PRUNE_OFFSCREEN=0` disables the pruning for diagnosis;
`find`/`wait` use other read purposes and still see hidden nodes.

Known limitation introduced by the at-spi2-core 2.44 workaround: menu items
and combo boxes do not get an action list from the walker (GetActions is
unsafe); `select` uses Selection and works, while activating a menu item
semantically may need the physical fallback. This is recorded as an open
follow-up rather than hidden.

Reliability pass (GNOME Wayland, 2026-11-09):

```
type_text "héllo 世界" via clipboard      → ok, clipboard_restored=true
  snapshot zenity entry                    → value "héllo 世界"
act click --x 10 --y 1000 --kernel         → mechanism "mutter-remote-desktop"
  (no /dev/uinput; kernel_input.accessible was false)
screencast, unapproved source dialog       → TIMEOUT after the consent budget
screencast, denied source dialog           → PERM_DENIED (response 1)
screencast request/gst/session unit tests  → 4 passed
desktop dogfood (--keep-existing)          → 20/20, screenshots=0
backend desktop suite                      → 72 passed
```

The ScreenCast path reached the portal's source dialog in both the timeout and
denial cases and failed closed; the successful frame path requires a person to
approve that dialog once. The restore token is then written and
`status.screencast_token` becomes true.

## 11. UX implemented so far

* **Settings > Computer use**: status (session, accessibility, kernel input,
  policy), "Check again", "Stop desktop control", the uinput setup commands,
  and the last six audit entries.
* **Sidebar**: a Computer Use item that opens the popup (settings fallback in
  a browser tab).
* **Agent wizard / inspector**: Desktop access and Desktop control toggles,
  a `desktop` tool pack, and a Desktop Copilot template.
* **Approvals**: `desktop_act`, `desktop_launch`, `desktop_screenshot` and
  `desktop_browser` are tier 2 / risk-listed, so the existing approval card and autonomy gates
  apply. Stop is available from Settings, the popup, the tray and the HTTP API.
* **Grant implies tools**: an agent with `desktop_access` or `desktop_control`
  receives the desktop pack at run time even when its `tool_pack` is `auto` or
  its hand-written tool list predates the pack. The tool router pins the
  observation/action set for desktop-looking tasks, and the orchestrator
  propagates the pack to its workers. This is what prevents a granted agent
  from answering "the desktop_* tools are not in my tool set". The native
  policy still enforces the grant and the per-app allowlist.
* **Popup** (`?window=computer-use`): redesigned from scratch as a compact
  command surface: brand header with live state, a **Target** list of every
  window on the desktop (deduplicated, own windows hidden), region selection
  with preview, a suggestion-assisted request composer, Ask/Act segmented
  control, an inline **Approve / Deny** card, streamed answer with copy,
  Stop, a footer model picker that switches the model for desktop runs, and a
  status rail. It works with no agent setup — `/api/desktop/ask`
  falls back to a transient Desktop Copilot with both desktop grants. Ask is
  read-only; Act streams `agent:waiting_for_human` into the approval card.
* **Region overlay** (`?window=region-overlay`): fullscreen transparent
  window with drag selection, size readout, Ask/Act/Retake/Cancel and Esc.
  The popup hides the overlay and waits before capturing, so the overlay is
  not in the image. The selection is cropped with Pillow using the native
  screenshot's scale factor and returned as a data-URL preview.
* **Global hotkeys**: `Super+Shift+C` opens the popup, `Ctrl+Shift+Escape`
  (Command+Shift+Escape on macOS) stops desktop control and releases held
  input; `Super+Shift+Space` remains the main-window toggle. Tray entries
  mirror open/stop.
* **Packaging**: `bundle.externalBin` includes `palimind-desktop`; the deb and
  AppImage produced on this host contain `usr/bin/palimind-desktop`. Building
  the bundles needs the appindicator development package
  (`libayatana-appindicator3-dev` on Ubuntu) because the Tauri CLI probes for
  it even though the runtime library is present.
* **Chromium web content**: `desktop_browser` uses CDP for page observation
  and actions when AT-SPI refs cannot be proven unique or a sandboxed browser
  hides its page. Palimind auto-discovers a running browser from
  `DevToolsActivePort`, the process command line, or the conventional ports
  (9222–9224); `PALIMIND_DESKTOP_CDP_PORT` or the tool's `port` argument still
  overrides it. `snapshot` returns the page's interactive elements with
  viewport bounds. No additional browser runtime is involved. The
  benchmark and an integration test verify click/fill/title/text and the
  ephemeral-port discovery path.
* **Ghost cursor**: optional click-through overlay (`?window=cursor-ghost`)
  created on demand by `show_ghost_cursor`. It draws a pulsing ring, dashed
  target rectangle and label without moving the real pointer and uses
  `set_ignore_cursor_events(true)`. Settings has a "Ghost cursor" toggle; the
  popup's "Show target" button demonstrates it on the selected region.
* **Annotation and OCR**: `desktop_screenshot(annotate=true)` draws the
  current snapshot's ref boxes with ref/role labels; `ocr=true` runs the local
  easyocr path and returns `ocr:<n>` boxes with confidence, marked
  `stable: false`. Annotation boxes are tested against snapshot bounds at
  scale 1, scale 2 with a crop offset, and window-relative bounds. On a
  Wayland snapshot whose window origin is unproven (0,0), annotation is
  refused with a clear error instead of drawing a misleading box; use OCR
  boxes or X11 for that case. Acting on an OCR box requires
  `confirm_destructive=true` and uses the kernel pointer with
  `coords_source=screenshot`.



## 12. Remaining work

* ScreenCast successful-frame approval: the portal handshake, restore-token
  persistence and PipeWire/GStreamer pipeline are implemented and unit-tested;
  on this host the first-use source dialog was not approved, so the run
  correctly ended in `TIMEOUT`/`PERM_DENIED`. A person must approve the dialog
  once; then `palimind-desktop screencast --out /tmp/shot.png` should write a
  PNG and `status.screencast_token` should become true.
* Flatpak Chromium browsers: `zen`/`brave` windows can now be resolved by
  alias, but a sandboxed browser that is not on the accessibility bus exposes
  only its menus. Page content still needs the CDP route or a shared a11y bus.
* Live canvas-app OCR verification through the desktop portal (this headless
  session denies capture; annotation/OCR are verified on generated images).
* KDE/wlroots best-effort validation.
* Packaged GUI runtime smoke: blocked here because the system path lacks
  `webkit2gtk-4.1/WebKitNetworkProcess` (the binary exists only in the local
  Tauri prefix). The bundles themselves are built and contain the sidecar.
* Real `/dev/uinput` injection after the udev rule/group setup (the code path
  was verified only to fail closed with `PERM_DENIED` on this host).
* Window-id-only snapshot p95 is ~155 ms because policy needs the app name;
  pass `app` with `window_id` when possible (app path p95 ~100 ms).
