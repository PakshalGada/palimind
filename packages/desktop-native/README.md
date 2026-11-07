# desktop-native

Linux desktop-control native layer for Palimind: a vendored AT-SPI2 engine plus
a thin `palimind-desktop` binary (CLI + stdio JSON-RPC daemon).

```
vendor/agent-desktop/   pinned agent-desktop v1.1.0 (Apache-2.0)
  crates/core/          platform-neutral engine (unmodified)
  crates/linux/         AT-SPI2 adapter (small local delta; see NOTICE)
  tests/, skills/       upstream fixtures and skill docs used by include_str!
palimind-desktop/       Palimind binary, policy, envelope, daemon, uinput
patches/                the complete upstream diff for rebases
```

Build and verify (from the repository root):

```bash
make desktop-native      # debug binary
make desktop-test        # vendored engine + wrapper tests
make desktop-lint        # clippy, warnings denied (toolchain pinned to 1.89)
make desktop-smoke       # status JSON
make desktop-bundle      # release binary staged for the Tauri sidecar
```

Run:

```bash
export PALIMIND_DESKTOP_ENABLE=1
export PALIMIND_DESKTOP_ALLOWED_APPS=gnome-calculator
palimind-desktop status
palimind-desktop apps windows
palimind-desktop snapshot --app gnome-calculator -i
palimind-desktop serve            # used by the Python backend
```

The state root is `~/.palimind/desktop` (override: `PALIMIND_DESKTOP_HOME`).
Screenshots are opt-in and local. `/dev/uinput` is opt-in and requires
`sudo scripts/install-uinput-udev.sh` (run from the repository root) plus a
re-login.

See `docs/computer-use.md` and `NOTICE`.
