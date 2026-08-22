from __future__ import annotations

import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class GPUInfo:
    name: str
    vram_mb: int
    backend: str  # cuda | rocm | metal | cpu


@dataclass
class HardwareProfile:
    gpus: List[GPUInfo] = field(default_factory=list)
    total_ram_mb: int = 0
    os_platform: str = ""  # linux | windows | macos
    wsl2_detected: bool = False
    serve_engines_available: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gpus": [
                {"name": g.name, "vram_mb": g.vram_mb, "backend": g.backend}
                for g in self.gpus
            ],
            "total_ram_mb": self.total_ram_mb,
            "os_platform": self.os_platform,
            "wsl2_detected": self.wsl2_detected,
            "serve_engines_available": self.serve_engines_available,
            "best_vram_mb": max((g.vram_mb for g in self.gpus), default=0),
            "gpu_count": len(self.gpus),
        }


def _run_cmd(cmd: list[str], timeout: int = 10) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def detect_nvidia_gpus() -> List[GPUInfo]:
    """Detect NVIDIA GPUs using nvidia-smi."""
    gpus = []
    output = _run_cmd(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    if not output:
        return gpus

    for line in output.strip().split("\n"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                name = parts[0]
                vram_mb = int(float(parts[1]))
                gpus.append(GPUInfo(name=name, vram_mb=vram_mb, backend="cuda"))
            except (ValueError, IndexError):
                continue
    return gpus


def detect_amd_gpus_linux() -> List[GPUInfo]:
    """Detect AMD GPUs using rocm-smi on Linux."""
    gpus = []
    output = _run_cmd(["rocm-smi", "--showmeminfo", "vram", "--json"])
    if output:
        try:
            data = json.loads(output)
            for card_key, card_data in data.items():
                if "card" in card_key.lower():
                    vram_total = card_data.get("VRAM Total Memory (B)", 0)
                    vram_mb = int(vram_total) // (1024 * 1024)
                    name = f"AMD GPU ({card_key})"
                    gpus.append(GPUInfo(name=name, vram_mb=vram_mb, backend="rocm"))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass

    if not gpus:
        output = _run_cmd(["rocminfo"])
        if output and "Marketing Name" in output:
            for line in output.split("\n"):
                if "Marketing Name" in line:
                    name = line.split(":")[-1].strip()
                    gpus.append(GPUInfo(name=name, vram_mb=0, backend="rocm"))
    return gpus


def detect_amd_gpus_windows() -> List[GPUInfo]:
    """Detect AMD GPUs using wmic on Windows (no ROCm on Windows)."""
    gpus = []
    output = _run_cmd(
        [
            "wmic",
            "path",
            "win32_VideoController",
            "get",
            "AdapterRAM,Name",
            "/format:csv",
        ]
    )
    if not output:
        return gpus

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line or "AdapterRAM" in line or "Node" in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                adapter_ram = int(parts[1]) if parts[1] else 0
                name = parts[2]
                if "AMD" in name.upper() or "RADEON" in name.upper():
                    vram_mb = adapter_ram // (1024 * 1024)
                    gpus.append(GPUInfo(name=name, vram_mb=vram_mb, backend="rocm"))
            except (ValueError, IndexError):
                continue
    return gpus


def detect_intel_igpu_windows() -> List[GPUInfo]:
    """Detect Intel iGPUs via wmic — these are CPU-only for inference."""
    gpus = []
    output = _run_cmd(
        [
            "wmic",
            "path",
            "win32_VideoController",
            "get",
            "AdapterRAM,Name",
            "/format:csv",
        ]
    )
    if not output:
        return gpus

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line or "AdapterRAM" in line or "Node" in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                name = parts[2]
                if (
                    "INTEL" in name.upper()
                    and "NVIDIA" not in name.upper()
                    and "AMD" not in name.upper()
                ):
                    adapter_ram = int(parts[1]) if parts[1] else 0
                    vram_mb = adapter_ram // (1024 * 1024) if adapter_ram > 0 else 0
                    gpus.append(GPUInfo(name=name, vram_mb=vram_mb, backend="cpu"))
            except (ValueError, IndexError):
                continue
    return gpus


def detect_apple_metal() -> List[GPUInfo]:
    """Detect Apple Silicon / Metal GPUs on macOS."""
    gpus = []
    output = _run_cmd(["system_profiler", "SPDisplaysDataType"])
    if not output:
        return gpus

    current_name = None
    for line in output.split("\n"):
        line = line.strip()
        if "Chipset Model:" in line:
            current_name = line.split(":")[-1].strip()
        elif "VRAM" in line and current_name:
            vram_str = line.split(":")[-1].strip()
            try:
                if "GB" in vram_str:
                    vram_mb = int(float(vram_str.replace("GB", "").strip()) * 1024)
                elif "MB" in vram_str:
                    vram_mb = int(float(vram_str.replace("MB", "").strip()))
                else:
                    vram_mb = 0
            except ValueError:
                vram_mb = 0
            gpus.append(GPUInfo(name=current_name, vram_mb=vram_mb, backend="metal"))
            current_name = None

    # Apple Silicon uses unified memory — use total RAM as "VRAM"
    if not gpus and output and "Apple" in output:
        import psutil

        total_ram_mb = psutil.virtual_memory().total // (1024 * 1024)
        for line in output.split("\n"):
            if "Chipset Model:" in line:
                name = line.split(":")[-1].strip()
                gpus.append(GPUInfo(name=name, vram_mb=total_ram_mb, backend="metal"))
                break

    return gpus


def detect_system_ram() -> int:
    """Detect total system RAM in MB."""
    try:
        import psutil

        return psutil.virtual_memory().total // (1024 * 1024)
    except ImportError:
        return 0


def detect_wsl2() -> bool:
    """Check if running under WSL2."""
    if platform.system() == "Linux":
        try:
            with open("/proc/version", "r") as f:
                version_info = f.read().lower()
                return "microsoft" in version_info
        except (FileNotFoundError, IOError):
            pass
    return False


def detect_serve_engines() -> List[str]:
    """Detect which model serving engines are available."""
    engines = []

    if shutil.which("ollama"):
        engines.append("ollama")

    if shutil.which("llama-server") or shutil.which("llama.cpp"):
        engines.append("llama.cpp")

    if platform.system() != "Windows":
        if shutil.which("vllm"):
            engines.append("vllm")
        if shutil.which("sglang"):
            engines.append("sglang")

    return engines


def detect_hardware() -> HardwareProfile:
    """Full hardware detection — returns a complete HardwareProfile."""
    os_name = platform.system()
    profile = HardwareProfile()

    # OS platform
    if os_name == "Windows":
        profile.os_platform = "windows"
    elif os_name == "Darwin":
        profile.os_platform = "macos"
    else:
        profile.os_platform = "linux"

    # GPUs
    nvidia_gpus = detect_nvidia_gpus()
    profile.gpus.extend(nvidia_gpus)

    if os_name == "Windows":
        amd_gpus = detect_amd_gpus_windows()
        intel_gpus = detect_intel_igpu_windows()
    elif os_name == "Darwin":
        amd_gpus = []
        metal_gpus = detect_apple_metal()
        profile.gpus.extend(metal_gpus)
        intel_gpus = []
    else:
        amd_gpus = detect_amd_gpus_linux()
        intel_gpus = []

    profile.gpus.extend(amd_gpus)
    profile.gpus.extend(intel_gpus)

    # System RAM
    profile.total_ram_mb = detect_system_ram()

    # WSL2
    profile.wsl2_detected = detect_wsl2()

    # Serve engines
    profile.serve_engines_available = detect_serve_engines()

    return profile
