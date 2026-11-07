# FFI Python smoke harness

Proves the C ABI works from a non-Rust host (Python ctypes) and gates it in CI.

## What it tests

| Leg | Check |
|-----|-------|
| 1 | `ad_abi_version()` equals `AD_ABI_VERSION_MAJOR` from the header. Catches a header and dylib mismatch at import. |
| 2 | Every `ad_*_size()` getter equals its `AD_*_SIZE` macro. Catches struct layout drift. |
| 3 | `ad_version()` returns `ok:true` JSON with `data.version`. |
| 4 | `ad_adapter_create` → `ad_snapshot` → `ad_free_string` → `ad_adapter_destroy` runs without a crash or leak. A stub adapter returns a clean `PLATFORM_NOT_SUPPORTED` envelope. |
| 5 | Opt-in with `AD_EXPECT_REAL=1` (optional `AD_APP`, default `gnome-calculator`). The real adapter returns a complete snapshot with refs for the app, on the main thread and on a worker thread. Run by `tests/linux-dist/run-consumer.sh`. |
| Linux helper | Opt-in with `AD_EXPECT_LINUX_HELPER=1` and `AD_HELPER_EMPTY_PATH`. Run by `scripts/ci-ffi-helper-discovery-smoke.sh`. With an empty `PATH`, the library finds the clipboard owner beside it, a foreign GTK reader sees the text it sets, and clear empties the selection. |
| 6 | Opt-in with `AD_EXPECT_MACOS_HELPER=1`. Run by `scripts/ci-ffi-helper-discovery-smoke.sh`. Checks macOS helper discovery. |

## Building the dylib

```bash
# From the repo root:
cargo build --locked --profile release-ffi -p agent-desktop-ffi --features stub-adapter
```

The dylib lands at `target/release-ffi/libagent_desktop_ffi.dylib` on macOS, or `target/release-ffi/libagent_desktop_ffi.so` on Linux.

Use `--profile release-ffi`. The default `release` profile sets `panic = "abort"`, which silently disables the FFI's `catch_unwind` traps.

`--features stub-adapter` replaces the real adapter with one that returns `PLATFORM_NOT_SUPPORTED` for every call. CI uses this build, so the harness runs without Accessibility permission.

## Running locally

The examples use macOS paths. On Linux, pass the `.so` instead.

```bash
python3 tests/ffi-python/smoke.py \
  target/release-ffi/libagent_desktop_ffi.dylib \
  crates/ffi/include/agent_desktop.h
```

Or set environment variables:

```bash
export AD_DYLIB_PATH=target/release-ffi/libagent_desktop_ffi.dylib
export AD_HEADER_PATH=crates/ffi/include/agent_desktop.h
python3 tests/ffi-python/smoke.py
```

## Stub enforcement (`AD_EXPECT_STUB=1`)

Set `AD_EXPECT_STUB=1` when you run the harness against a stub build. The harness then fails if `ad_snapshot()` returns `ok:true`, which would mean the dylib was not built with `--features stub-adapter`. The arm64 macOS leg of the `ffi-panic-guard` CI job sets this variable. A real-adapter dylib therefore cannot pass the stub gate.

## Dependencies

`smoke.py` uses only the Python standard library, so no `pip install` is needed. The Linux helper leg is the exception. `linux_helper.py` reads the clipboard as a foreign GTK client, so it needs PyGObject with the GTK 3 typelib (`python3-gi` and `gir1.2-gtk-3.0`).

## Real-adapter happy path

Legs 1 to 4 cover the surface that needs no permission: the ABI version, struct sizes, `ad_version`, and the `PLATFORM_NOT_SUPPORTED` path. A successful `ad_snapshot` from the real adapter is tested elsewhere. On macOS, `tests/e2e/run.sh` covers it through `scenarios/acceptance.sh`, which runs `ffi_live.py` against the release FFI library. That run needs Accessibility permission. On Linux, leg 5 covers it.

## Other files

| File | Purpose |
|------|---------|
| `linux_helper.py` | The Linux helper leg, and `verify_cli` for the installed CLI (used by `tests/linux-dist/run-npm-install.sh`) |
| `test_linux_helper.py` | Unit tests for `linux_helper.py`: `python3 -I -m unittest discover -s tests/ffi-python -p 'test_linux_helper.py'` |
| `leak_probe.py` | Linux only, not run by CI: `python3 tests/ffi-python/leak_probe.py <library.so> [--calls N]`. It points the library at a silent X11 TCP server and checks that repeated timed-out `ad_list_displays` calls keep the host's thread and descriptor counts flat. |
