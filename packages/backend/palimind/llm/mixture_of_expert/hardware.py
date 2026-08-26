from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HardwareEstimate:
    vram_per_worker_mb: int
    vram_orchestrator_mb: int
    total_vram_needed_mb: int
    total_ram_needed_mb: int
    fits_gpu: bool
    fits_ram: bool
    suggested_worker: str = ""
    suggested_orchestrator: str = ""


MODEL_VRAM_ESTIMATES: dict[str, int] = {
    "gemma4:e2b": 2048,
    "gemma4:2b": 1024,
    "gemma:2b": 1024,
    "gemma:7b": 4096,
    "llama3.2:1b": 768,
    "llama3.2:3b": 2048,
    "llama3.1:8b": 6144,
    "llama3:8b": 6144,
    "llama3:70b": 40960,
    "mistral:7b": 4096,
    "mixtral:8x7b": 24576,
    "phi3:3.8b": 2048,
    "phi3:14b": 8192,
    "qwen2.5:0.5b": 512,
    "qwen2.5:1.5b": 1024,
    "qwen2.5:3b": 2048,
    "qwen2.5:7b": 4096,
    "qwen2.5:14b": 8192,
    "qwen2.5:32b": 20480,
    "qwen2.5:72b": 40960,
    "deepseek-coder:6.7b": 4096,
    "deepseek-coder:33b": 20480,
    "deepseek-coder-v2": 32768,
    "nomic-embed-text": 256,
    "llava": 4096,
    "llava:7b": 4096,
    "llava:13b": 8192,
}


def estimate_model_vram(model_name: str) -> int:
    exact = MODEL_VRAM_ESTIMATES.get(model_name)
    if exact is not None:
        return exact
    parts = model_name.split(":")
    if len(parts) > 1:
        size_part = parts[1]
        import re

        match = re.match(r"(\d+)", size_part)
        if match:
            size_val = int(match.group(1))
            if size_val <= 1:
                return 768
            elif size_val <= 3:
                return 2048
            elif size_val <= 7:
                return 4096
            elif size_val <= 14:
                return 8192
            elif size_val <= 33:
                return 20480
            elif size_val <= 72:
                return 40960
            else:
                return 65536
    return 6144


def estimate_hardware_requirements(
    orchestrator_model: str,
    worker_model: str,
    num_workers: int = 4,
    gpu_vram_mb: int = 0,
    system_ram_mb: int = 0,
) -> HardwareEstimate:
    vram_orch = estimate_model_vram(orchestrator_model)
    vram_worker = estimate_model_vram(worker_model)
    total_vram = vram_orch + (vram_worker * num_workers)
    total_ram = total_vram * 2
    overhead_orch = vram_orch + 512
    overhead_worker = vram_worker + 256
    fits_gpu = True
    if gpu_vram_mb > 0:
        layered_orch = 192
        layered_worker = 192
        (vram_orch - layered_orch) // 32
        (vram_worker - layered_worker) // 32
        sequential_vram = max(overhead_orch, overhead_worker)
        fits_gpu = sequential_vram <= gpu_vram_mb
    fits_ram = True
    if system_ram_mb > 0:
        fits_ram = total_ram <= system_ram_mb
    recommendation_orch = orchestrator_model
    recommendation_worker = worker_model
    if not fits_gpu and gpu_vram_mb > 0:
        for candidate, vram in sorted(MODEL_VRAM_ESTIMATES.items(), key=lambda x: x[1]):
            if vram <= gpu_vram_mb - 512 and vram > estimate_model_vram(worker_model):
                recommendation_orch = candidate
                break
        recommendation_worker = "qwen2.5:1.5b"
        if gpu_vram_mb < 2048:
            recommendation_worker = "qwen2.5:0.5b"
    if not fits_ram and system_ram_mb > 0:
        recommendation_orch = "qwen2.5:7b"
        recommendation_worker = "qwen2.5:1.5b"

    return HardwareEstimate(
        vram_per_worker_mb=vram_worker,
        vram_orchestrator_mb=vram_orch,
        total_vram_needed_mb=total_vram,
        total_ram_needed_mb=total_ram,
        fits_gpu=fits_gpu,
        fits_ram=fits_ram,
        suggested_worker=recommendation_worker,
        suggested_orchestrator=recommendation_orch,
    )
