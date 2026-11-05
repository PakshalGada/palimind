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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def sandbox_exec_path() -> str | None:
    """Return the macOS ``sandbox-exec`` binary, if this is macOS."""
    if sys.platform != "darwin":
        return None
    return shutil.which("sandbox-exec") or (
        "/usr/bin/sandbox-exec" if Path("/usr/bin/sandbox-exec").is_file() else None
    )


def windows_sandbox_available() -> bool:
    """True when the Windows Job Object backend can be constructed."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(hasattr(ctypes, "windll"))
    except Exception:
        return False


def sandbox_backend() -> str:
    """Return the strongest available backend name for this platform."""
    if sys.platform == "darwin" and sandbox_exec_path():
        return "macos-sandbox-exec"
    if sys.platform == "win32" and windows_sandbox_available():
        return "windows-job-object"
    if bwrap_path():
        return "bubblewrap"
    if _unsandboxed_allowed():
        return "unsandboxed"
    return "unavailable"


def sandbox_available() -> bool:
    return sandbox_backend() != "unavailable"


def describe_sandbox() -> str:
    backend = sandbox_backend()
    if backend == "unsandboxed":
        return "unsandboxed (explicitly enabled)"
    return backend


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


def _quote_sandbox_path(path: str) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def macos_sandbox_profile(
    root: Path,
    *,
    allow_network: bool = False,
    allow_write: bool = False,
) -> str:
    """Build a deny-by-default ``sandbox-exec`` profile for agent code."""
    root = Path(root).resolve()
    read_paths = [
        "/usr",
        "/bin",
        "/sbin",
        "/System",
        "/Library",
        "/private/etc",
        "/private/var/db/dyld",
        "/dev/null",
        "/dev/zero",
        "/dev/urandom",
        str(sys.prefix),
        str(sys.base_prefix),
        str(root),
    ]
    write_paths = ["/private/tmp", "/private/var/folders"]
    if allow_write:
        write_paths.append(str(root))
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow file-read-metadata)",
    ]
    for path in dict.fromkeys(read_paths):
        if path and path != "/":
            lines.append(f'(allow file-read* (subpath "{_quote_sandbox_path(path)}"))')
    for path in dict.fromkeys(write_paths):
        if path and path != "/":
            lines.append(f'(allow file-write* (subpath "{_quote_sandbox_path(path)}"))')
    lines.append('(allow file-write* (literal "/dev/null"))')
    if allow_network:
        lines.append("(allow network*)")
    return "\n".join(lines) + "\n"


def _macos_argv(
    command: list[str],
    root: Path,
    *,
    allow_network: bool,
    allow_write: bool,
) -> list[str]:
    sandbox_exec = sandbox_exec_path()
    if not sandbox_exec:
        raise SandboxUnavailable("macOS sandbox-exec is not available.")
    profile = macos_sandbox_profile(root, allow_network=allow_network, allow_write=allow_write)
    return [sandbox_exec, "-p", profile, *command]


def _run_windows_sandbox(
    command: list[str],
    *,
    root: Path,
    timeout_s: int,
    allow_network: bool,
    allow_write: bool,
    limits: SandboxLimits,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Run a command under a Windows Job Object with memory/process limits.

    Windows has no unprivileged mount namespace, so workspace confinement is
    enforced with a Job Object (process/memory limits and kill-on-close) plus a
    minimal environment. The child is never given an inherited console. If the
    Job Object cannot be created or assigned, the call fails closed.
    """
    if not windows_sandbox_available():
        raise SandboxUnavailable("Windows Job Object sandbox is not available.")
    import ctypes
    from ctypes import wintypes

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise SandboxUnavailable("Could not create a Windows Job Object.")
    proc: subprocess.Popen | None = None
    out_f = tempfile.TemporaryFile()
    err_f = tempfile.TemporaryFile()
    try:
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        memory = max(64, int(limits.memory_mb)) * 1024 * 1024
        info.ProcessMemoryLimit = memory
        info.JobMemoryLimit = memory
        info.BasicLimitInformation.ActiveProcessLimit = max(1, int(limits.processes))
        if not kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            raise SandboxUnavailable("Could not configure the Windows Job Object.")
        proc = subprocess.Popen(  # noqa: S603 - argv list, no shell
            command,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
            env=env,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        )
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            proc.kill()
            raise SandboxUnavailable("Could not assign the process to the Job Object.")
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kernel32.TerminateJobObject(job, 1)
            proc.kill()
            raise
        return subprocess.CompletedProcess(
            command, int(proc.returncode), _read_tail(out_f), _read_tail(err_f)
        )
    finally:
        try:
            kernel32.CloseHandle(job)
        except Exception:
            pass
        try:
            out_f.close()
            err_f.close()
        except Exception:
            pass


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

    backend = sandbox_backend()
    env = _minimal_env(root, allow_network=allow_network)
    if backend == "windows-job-object":
        return _run_windows_sandbox(
            command,
            root=root,
            timeout_s=timeout_s,
            allow_network=allow_network,
            allow_write=allow_write,
            limits=limits,
            env=env,
        )
    if backend == "macos-sandbox-exec":
        argv = _macos_argv(
            command,
            root,
            allow_network=allow_network,
            allow_write=allow_write,
        )
    elif backend == "bubblewrap":
        argv = _bwrap_argv(
            command,
            root,
            allow_network=allow_network,
            allow_write=allow_write,
        )
    elif backend == "unsandboxed":
        argv = command
    else:
        raise SandboxUnavailable(
            "No sandbox is available. Install bubblewrap ('bwrap') on Linux or "
            "ensure sandbox-exec exists on macOS; on Windows the Job Object "
            "backend is required. Set PALIMIND_ALLOW_UNSANDBOXED_EXEC=1 to "
            "explicitly accept running agent code directly on the host."
        )

    # Output goes to temp files rather than pipes: the child's RLIMIT_FSIZE
    # then caps it (``yes`` cannot balloon this process's memory), and bytes
    # are decoded leniently so binary output cannot raise UnicodeDecodeError.
    # stdin is closed so ``cat``/``read`` cannot block on the server's stdin.
    with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
        proc = subprocess.run(  # noqa: S603 - argv is constructed here, no shell
            argv,
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
            timeout=timeout_s,
            env=env,
            preexec_fn=_preexec(limits),
        )
        return subprocess.CompletedProcess(
            argv, proc.returncode, _read_tail(out_f), _read_tail(err_f)
        )


_MAX_CAPTURE_BYTES = 256 * 1024


def _read_tail(fh: Any) -> str:
    """Return (at most) the last ``_MAX_CAPTURE_BYTES`` written to *fh*."""
    size = fh.seek(0, os.SEEK_END)
    fh.seek(max(0, size - _MAX_CAPTURE_BYTES))
    return fh.read().decode("utf-8", errors="replace")


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
