#!/usr/bin/env bash
# Opt-in kernel input for Palimind computer use.
#
# Creates a udev rule that lets members of the "input" group open /dev/uinput,
# loads the uinput module, and adds the invoking user (when run via sudo) to
# that group. Palimind does not install a setuid helper: this is the documented
# privilege boundary for the kernel input backend.
#
# Usage:
#   sudo scripts/install-uinput-udev.sh            # install
#   sudo scripts/install-uinput-udev.sh --uninstall
#
# Re-login (or `newgrp input`) after installation so the group membership
# applies to your session.
set -euo pipefail

RULE_PATH="/etc/udev/rules.d/99-palimind-uinput.rules"
RULE_LINE='KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'

if [[ "${EUID}" -ne 0 ]]; then
  echo "error: run with sudo (this script writes a udev rule and group membership)" >&2
  exit 1
fi

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "${RULE_PATH}"
  udevadm control --reload-rules
  echo "Removed ${RULE_PATH}. The 'input' group membership was left unchanged."
  exit 0
fi

if ! command -v udevadm >/dev/null 2>&1; then
  echo "error: udevadm not found; install udev/systemd first" >&2
  exit 1
fi

modprobe uinput 2>/dev/null || echo "warning: could not load uinput module; it may be built in"

umask 022
printf '%s\n' "${RULE_LINE}" > "${RULE_PATH}"
udevadm control --reload-rules
udevadm trigger /dev/uinput 2>/dev/null || true

if [[ -n "${SUDO_USER:-}" ]]; then
  if id -nG "${SUDO_USER}" | tr ' ' '\n' | grep -qx input; then
    echo "${SUDO_USER} is already in the 'input' group"
  else
    usermod -aG input "${SUDO_USER}"
    echo "Added ${SUDO_USER} to the 'input' group"
  fi
fi

echo
echo "Installed ${RULE_PATH}"
echo "Sign out and back in (or run 'newgrp input') before starting Palimind."
echo "Verify with: palimind-desktop status   # kernel_input.accessible should be true"
