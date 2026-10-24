"""OS-level isolation for agent shell/Python execution.

The previous implementation only set ``cwd`` for ``subprocess.run`` which is
not a sandbox at all: absolute paths, ``..`` traversal, environment secrets and
network access all worked.  This module builds an actual isolation boundary.

On Linux we use bubblewrap (``bwrap``), the same unprivileged sandbox used by
Flatpak:

* all namespaces unshared (user, pid, mount, ipc, uts, cgroup) and **no
  network** unless the caller explicitly opts in;
* the host filesystem is mounted read-only; only the active workspace is
  writable, and only when the agent has ``write_access``;
* a private ``/tmp`` tmpfs, ``/proc`` and ``/dev``;
* a minimal environment (no inherited API keys/tokens);
* resource limits (address space, CPU time, file size, open files, processes).

If bubblewrap is unavailable we **fail closed**.  Running untrusted model
output directly on the host is never an acceptable fallback; operators can
explicitly acknowledge the risk with ``PALIMIND_ALLOW_UNSANDBOXED_EXEC=1``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from palimind.settings import (
    PYTHON_EXEC_CPU_TIME,
    PYTHON_EXEC_MEMORY_MB,
    PYTHON_EXEC_TIMEOUT,
    SHELL_EXEC_TIMEOUT,
)


class SandboxUnavailable(RuntimeError):
    """Raised when no real sandbox can be constructed."""


@dataclass(frozen=True)
class SandboxLimits:
    timeout_s: int
    memory_mb: int = PYTHON_EXEC_MEMORY_MB
    cpu_seconds: float = PYTHON_EXEC_CPU_TIME
    file_size_mb: int = 64
    open_files: int = 256
    processes: int = 256


def _unsandboxed_allowed() -> bool:
    return os.environ.get("PALIMIND_ALLOW_UNSANDBOXED_EXEC", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def bwrap_path() -> str | None:
    return shutil.which("bwrap")


def sandbox_available() -> bool:
    return bwrap_path() is not None or _unsandboxed_allowed()


def describe_sandbox() -> str:
    if bwrap_path():
        return "bubblewrap"
    if _unsandboxed_allowed():
        return "unsandboxed (explicitly enabled)"
    return "unavailable"


def _minimal_env(root: Path, *, allow_network: bool) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if allow_network:
        # Proxy variables are deliberately not inherited: network access, when
        # enabled, should go direct rather than through a user's credentials.
        pass
    return env


def _bwrap_argv(
    command: list[str],
    root: Path,
    *,
    allow_network: bool,
    allow_write: bool,
) -> list[str]:
    bwrap = bwrap_path()
    if not bwrap:
        raise SandboxUnavailable(
            "bubblewrap (bwrap) is not installed. Install it (e.g. 'sudo apt install "
            "bubblewrap') or set PALIMIND_ALLOW_UNSANDBOXED_EXEC=1 to explicitly accept "
            "running agent code directly on the host."
        )

    root = root.resolve()
    argv = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop",
        "ALL",
        "--clearenv",
    ]

    # Do NOT bind the host root: that exposes /etc/passwd, SSH keys, other
    # workspaces and the user's home directory. Bind only the runtime pieces
    # needed to start an interpreter/shell.
    runtime_paths = [
        "/usr",
        "/usr/local",
        "/lib",
        "/lib32",
        "/lib64",
        "/bin",
        "/sbin",
        "/etc/ld.so.cache",
        "/etc/ld.so.conf",
        "/etc/ld.so.conf.d",
        "/etc/alternatives",
        "/etc/ssl",
        "/etc/ca-certificates",
        "/etc/fonts",
        "/etc/localtime",
        "/etc/nsswitch.conf",
    ]
    if allow_network:
        runtime_paths += ["/etc/resolv.conf", "/etc/hosts"]
    # The active interpreter (often a venv under the user's home) and its base
    # installation are required for imports.
    for candidate in {
        sys.prefix,
        sys.base_prefix,
        str(Path(sys.executable).resolve().parent.parent),
    }:
        if candidate and candidate not in ("/", ""):
            runtime_paths.append(candidate)

    seen: set[str] = set()
    for path in runtime_paths:
        if path in seen:
            continue
        seen.add(path)
        argv += ["--ro-bind-try", path, path]

    argv += [
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--chdir",
        str(root),
    ]
    if allow_network:
        argv.append("--share-net")
    # When the workspace *is* /tmp the tmpfs above already provides a private,
    # writable mount; binding over it would make /tmp read-only.
    if root != Path("/tmp"):
        if allow_write:
            argv += ["--bind", str(root), str(root)]
        else:
            argv += ["--ro-bind", str(root), str(root)]

    for key, value in _minimal_env(root, allow_network=allow_network).items():
        argv += ["--setenv", key, value]
    argv.append("--")
    argv.extend(command)
    return argv


def _preexec(limits: SandboxLimits):
    """Return a preexec hook applying resource limits (POSIX only)."""

    def _apply() -> None:  # pragma: no cover - runs in the child process
        try:
            import resource

            memory = max(64, int(limits.memory_mb)) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            cpu = max(1, int(limits.cpu_seconds))
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
            fsize = max(1, int(limits.file_size_mb)) * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
            # RLIMIT_NPROC is per *user*, not per process: a low value makes
            # bwrap's clone() fail when the desktop already runs many tasks.
            # Use a generous cap that still prevents fork bombs.
            try:
                resource.setrlimit(resource.RLIMIT_NPROC, (4096, 4096))
            except (ValueError, OSError):
                pass
        except (ImportError, OSError, ValueError):
            pass

    return _apply if sys.platform != "win32" else None


def run_command(
    command: list[str],
    *,
    root: Path,
    timeout_s: int,
    allow_network: bool = False,
    allow_write: bool = False,
    memory_mb: int = PYTHON_EXEC_MEMORY_MB,
    cpu_seconds: float = PYTHON_EXEC_CPU_TIME,
) -> subprocess.CompletedProcess[str]:
    """Run *command* inside the strongest available sandbox.

    Raises :class:`SandboxUnavailable` when no real boundary can be built and
    the operator has not explicitly opted into unsandboxed execution.
    """
    if not root.is_dir():
        raise SandboxUnavailable(f"workspace root does not exist: {root}")

    limits = SandboxLimits(
        timeout_s=timeout_s,
        memory_mb=memory_mb,
        cpu_seconds=cpu_seconds,
    )

    if bwrap_path():
        argv = _bwrap_argv(
            command,
            root,
            allow_network=allow_network,
            allow_write=allow_write,
        )
        env = _minimal_env(root, allow_network=allow_network)
    elif _unsandboxed_allowed():
        argv = command
        env = _minimal_env(root, allow_network=allow_network)
    else:
        raise SandboxUnavailable(
            "No sandbox is available. Install bubblewrap ('bwrap') or set "
            "PALIMIND_ALLOW_UNSANDBOXED_EXEC=1 to explicitly accept running agent "
            "code directly on the host."
        )

    return subprocess.run(  # noqa: S603 - argv is constructed here, no shell
        argv,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        preexec_fn=_preexec(limits),
    )


def _format_result(proc: subprocess.CompletedProcess[str]) -> str:
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        parts = [f"Error (exit {proc.returncode})"]
        if err:
            parts.append(err[-2000:])
        if out:
            parts.append(out[-2000:])
        return "\n".join(parts)
    parts = []
    if out:
        parts.append(out[-4000:])
    if err:
        parts.append(f"[stderr]\n{err[-2000:]}")
    return "\n".join(parts) if parts else "Command completed successfully (no output)"


def run_shell_isolated(
    command: str,
    *,
    root: Path,
    allow_network: bool = False,
    allow_write: bool = False,
    timeout_s: int | None = None,
) -> str:
    """Execute *command* via ``/bin/sh -c`` inside the sandbox."""
    if not isinstance(command, str) or not command.strip():
        return "Error: command is required"
    timeout = int(timeout_s or SHELL_EXEC_TIMEOUT)
    try:
        proc = run_command(
            ["/bin/sh", "-c", command],
            root=root,
            timeout_s=timeout,
            allow_network=allow_network,
            allow_write=allow_write,
            memory_mb=PYTHON_EXEC_MEMORY_MB,
            cpu_seconds=PYTHON_EXEC_CPU_TIME,
        )
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except SandboxUnavailable as exc:
        return f"Error: sandbox unavailable — {exc}"
    except OSError as exc:
        return f"Error running command: {exc}"
    return _format_result(proc)


def run_python_isolated(
    code: str,
    *,
    root: Path,
    timeout_s: int | None = None,
    allow_network: bool = False,
    allow_write: bool = False,
) -> str:
    """Execute *code* with an isolated Python interpreter inside the sandbox."""
    if not code or not str(code).strip():
        return "Error: code is required"
    timeout = int(timeout_s or PYTHON_EXEC_TIMEOUT)
    # Keep the user's interpreter (so the venv's packages are available) but
    # run it isolated (-I): no user site, no PYTHON* env, no cwd on sys.path.
    # Resolve symlinks/`..` because bwrap execs the path verbatim inside the
    # minimal mount namespace.
    interpreter = str(Path(sys.executable).resolve())
    argv = [interpreter, "-I", "-c", str(code)]
    try:
        proc = run_command(
            argv,
            root=root,
            timeout_s=timeout,
            allow_network=allow_network,
            allow_write=allow_write,
            memory_mb=PYTHON_EXEC_MEMORY_MB,
            cpu_seconds=PYTHON_EXEC_CPU_TIME,
        )
    except subprocess.TimeoutExpired:
        return f"Error: execution exceeded {timeout}s timeout"
    except SandboxUnavailable as exc:
        return f"Error: sandbox unavailable — {exc}"
    except OSError as exc:
        return f"Error: failed to start interpreter ({exc})"
    return _format_result(proc)
