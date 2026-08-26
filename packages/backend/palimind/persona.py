from __future__ import annotations

from pathlib import Path


def get_persona(field_root: Path | None) -> dict[str, str]:
    """Return {name, system_prompt} for the active field (empty strings if unset)."""
    if field_root is None:
        return {"name": "", "system_prompt": ""}
    try:
        from palimind.config import load_config

        cfg = load_config(field_root)
        return {
            "name": str(cfg.get("persona_name", "") or ""),
            "system_prompt": str(cfg.get("persona_system_prompt", "") or ""),
        }
    except Exception:
        return {"name": "", "system_prompt": ""}


def persona_block(field_root: Path | None) -> str:
    """Render the persona as a prompt block, or '' when no persona is set."""
    persona = get_persona(field_root)
    name = persona["name"]
    prompt = persona["system_prompt"].strip()
    if not prompt:
        return ""
    label = f"Your name is {name}." if name else ""
    return (
        "[PERSONA]\n"
        + (f"{label} " if label else "")
        + "Follow these persona instructions in every reply:\n"
        + prompt
    ).strip()
