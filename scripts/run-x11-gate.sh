#!/usr/bin/env bash
# Run the X11 release gate on a nested Xephyr display.
#
# Requires: Xephyr, openbox (or OPENBOX_BIN), and a built palimind-desktop.
# This is the CI/local stand-in for a real X11 login. It does not need root.
#
#   ./scripts/run-x11-gate.sh
#   OPENBOX_BIN=/path/to/openbox LD_LIBRARY_PATH=/path/to/libs \
#     OPENBOX_CONFIG=/tmp/obrc.xml XDG_DATA_DIRS=/tmp:/usr/share \
#     ./scripts/run-x11-gate.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPLAY_NUM="${DISPLAY_NUM:-:50}"
REPORT="${REPORT:-/tmp/palimind-x11.json}"
STARTED_XEPHYR=0
XPID=""
OPID=""

cleanup() {
  if [[ -n "${OPID}" ]]; then kill "${OPID}" 2>/dev/null || true; fi
  if [[ "${STARTED_XEPHYR}" == "1" && -n "${XPID}" ]]; then kill "${XPID}" 2>/dev/null || true; fi
}
trap cleanup EXIT

if ! command -v Xephyr >/dev/null 2>&1; then
  echo "error: Xephyr not installed; install xserver-xephyr or use a real X11 login" >&2
  exit 2
fi

if ! xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then
  Xephyr "${DISPLAY_NUM}" -screen 1280x800 -ac -noreset >/tmp/palimind-xephyr.log 2>&1 &
  XPID=$!
  STARTED_XEPHYR=1
  for _ in $(seq 1 20); do
    if xdpyinfo -display "${DISPLAY_NUM}" >/dev/null 2>&1; then break; fi
    sleep 0.25
  done
fi

OPENBOX_BIN="${OPENBOX_BIN:-$(command -v openbox || true)}"
if [[ -z "${OPENBOX_BIN}" || ! -x "${OPENBOX_BIN}" ]]; then
  echo "error: openbox not found; set OPENBOX_BIN or install openbox" >&2
  exit 2
fi

if [[ -n "${OPENBOX_CONFIG:-}" ]]; then
  DISPLAY="${DISPLAY_NUM}" "${OPENBOX_BIN}" --config-file "${OPENBOX_CONFIG}" >/tmp/palimind-openbox.log 2>&1 &
else
  DISPLAY="${DISPLAY_NUM}" "${OPENBOX_BIN}" >/tmp/palimind-openbox.log 2>&1 &
fi
OPID=$!
sleep 1

DISPLAY="${DISPLAY_NUM}" XDG_SESSION_TYPE=x11 \
  env -u WAYLAND_DISPLAY \
  PALIMIND_DESKTOP_BIN="${PALIMIND_DESKTOP_BIN:-${ROOT}/apps/desktop/src-tauri/binaries/palimind-desktop-$(rustc -vV | awk '/^host:/{print $2}')}" \
  "${PY_BIN:-${ROOT}/.venv/bin/python}" "${ROOT}/scripts/x11_validation.py" --json "${REPORT}"
RC=$?
cat "${REPORT}"
exit "${RC}"
