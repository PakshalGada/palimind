"""Platform-gated tests for the sandbox backends."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from palimind.security import sandbox


def test_linux_backend_uses_bubblewrap(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    monkeypatch.setattr(sandbox, "sandbox_exec_path", lambda: None)
    assert sandbox.sandbox_backend() == "bubblewrap"
    assert sandbox.describe_sandbox() == "bubblewrap"
    argv = sandbox._bwrap_argv(["echo", "hi"], tmp_path, allow_network=False, allow_write=False)
    assert argv[0] == "/usr/bin/bwrap"
    assert "--unshare-all" in argv
    assert "--share-net" not in argv


def test_macos_profile_denies_network_and_writes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "sandbox_exec_path", lambda: "/usr/bin/sandbox-exec")
    profile = sandbox.macos_sandbox_profile(tmp_path, allow_network=False, allow_write=False)
    assert "(deny default)" in profile
    assert "(allow process*)" in profile
    assert str(tmp_path) in profile
    assert "(allow network*)" not in profile
    assert f'(allow file-write* (subpath "{tmp_path}"))' not in profile

    writable = sandbox.macos_sandbox_profile(tmp_path, allow_network=True, allow_write=True)
    assert "(allow network*)" in writable
    assert f'(allow file-write* (subpath "{tmp_path}"))' in writable

    argv = sandbox._macos_argv(
        ["/bin/echo", "hi"], tmp_path, allow_network=False, allow_write=False
    )
    assert argv[0] == "/usr/bin/sandbox-exec"
    assert argv[1] == "-p"
    assert argv[-2:] == ["/bin/echo", "hi"]


def test_macos_backend_detection(monkeypatch) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "darwin")
    monkeypatch.setattr(sandbox, "sandbox_exec_path", lambda: "/usr/bin/sandbox-exec")
    assert sandbox.sandbox_backend() == "macos-sandbox-exec"
    assert sandbox.sandbox_available() is True


def test_windows_backend_detection_and_fail_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "win32")
    monkeypatch.setattr(sandbox, "windows_sandbox_available", lambda: True)
    assert sandbox.sandbox_backend() == "windows-job-object"

    monkeypatch.setattr(sandbox, "windows_sandbox_available", lambda: False)
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox._run_windows_sandbox(
            ["cmd"],
            root=tmp_path,
            timeout_s=1,
            allow_network=False,
            allow_write=False,
            limits=sandbox.SandboxLimits(timeout_s=1),
            env={},
        )


def test_run_command_dispatches_windows_job(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "win32")
    monkeypatch.setattr(sandbox, "windows_sandbox_available", lambda: True)
    seen: dict = {}

    def fake_windows(command, **kwargs):
        seen.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(sandbox, "_run_windows_sandbox", fake_windows)
    proc = sandbox.run_command(["cmd", "/c", "echo hi"], root=tmp_path, timeout_s=5)
    assert proc.returncode == 0
    assert seen["command"] == ["cmd", "/c", "echo hi"]


def test_unavailable_backend_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sandbox.sys, "platform", "linux")
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: None)
    monkeypatch.setattr(sandbox, "sandbox_exec_path", lambda: None)
    monkeypatch.setattr(sandbox, "_unsandboxed_allowed", lambda: False)
    monkeypatch.setattr(sandbox, "windows_sandbox_available", lambda: False)
    assert sandbox.sandbox_available() is False
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.run_command(["echo", "hi"], root=tmp_path, timeout_s=5)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only sandbox")
def test_macos_real_sandbox_blocks_network(tmp_path: Path) -> None:  # pragma: no cover
    proc = sandbox.run_command(
        ["/usr/bin/curl", "-sS", "--max-time", "2", "https://example.com"],
        root=tmp_path,
        timeout_s=5,
        allow_network=False,
    )
    assert proc.returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only sandbox")
def test_windows_real_sandbox_runs(tmp_path: Path) -> None:  # pragma: no cover
    proc = sandbox.run_command(["cmd", "/c", "echo hi"], root=tmp_path, timeout_s=5)
    assert proc.returncode == 0
    assert "hi" in proc.stdout
