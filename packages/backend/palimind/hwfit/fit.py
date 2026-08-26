from __future__ import annotations

QUALITY_WEIGHTS = {
    "best": 1.0,
    "fp8": 0.9,
    "awq": 0.8,
    "good": 0.7,
    "q5": 0.6,
    "q4": 0.5,
    "q3": 0.4,
}
FIT_PERFECTLY = "FITS_PERFECTLY"
FIT_TIGHT = "FITS_TIGHT"
CPU_FALLBACK = "CPU_FALLBACK"
TOO_LARGE = "TOO_LARGE"


def compute_fit(vram_mb: int, ram_mb: int, quant_vram: int) -> tuple[str, float]:
    if vram_mb > 0 and quant_vram <= vram_mb * 0.85:
        return FIT_PERFECTLY, 1.0
    if vram_mb > 0 and quant_vram <= vram_mb:
        return FIT_TIGHT, 0.75
    if quant_vram <= ram_mb * 0.80:
        return CPU_FALLBACK, 0.35
    return TOO_LARGE, 0.0


def rank_models(hardware, catalog: list[dict], top: int = 20) -> list[dict]:
    best_vram = max((g.vram_mb for g in hardware.gpus), default=0)
    ram = hardware.total_ram_mb
    results = []

    for model in catalog:
        if not model.get("quants"):
            continue
        best_quant = model["quants"][0]
        for q in model["quants"]:
            qw = QUALITY_WEIGHTS.get(q["quality"], 0.5)
            bw = QUALITY_WEIGHTS.get(best_quant["quality"], 0.5)
            if q["vram_mb"] <= best_vram * 0.90 and qw >= bw:
                best_quant = q
            elif q["vram_mb"] <= best_vram and qw > bw:
                best_quant = q

        fit_label, fit_base = compute_fit(best_vram, ram, best_quant["vram_mb"])
        quality_w = QUALITY_WEIGHTS.get(best_quant["quality"], 0.5)
        speed_bonus = 0
        if best_vram > 0 and best_quant["vram_mb"] > 0:
            speed_bonus = min(1.0, best_vram / best_quant["vram_mb"]) * 0.3
        score = round(fit_base * 0.5 + quality_w * 0.3 + speed_bonus * 0.2, 3)

        results.append(
            {
                "id": model["id"],
                "name": model["name"],
                "family": model["family"],
                "params_b": model["params_b"],
                "best_quant": best_quant["tag"],
                "vram_required_mb": best_quant["vram_mb"],
                "file_size_gb": best_quant["file_size_gb"],
                "fit": fit_label,
                "score": score,
                "use_cases": model["use_cases"],
                "tags": model["tags"],
            }
        )

    results.sort(key=lambda x: (-x["score"], x["vram_required_mb"]))
    return results[:top]
