"""Generate a local image with the optional ComfyUI/sd.cpp backend."""

from __future__ import annotations

from typing import Any


def image_generate(
    prompt: str,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    seed: int | None = None,
) -> str:
    from palimind.imagegen import generate_and_save

    try:
        image = generate_and_save(
            prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            seed=seed,
        )
    except Exception as exc:  # noqa: BLE001 - tools return text errors
        return f"Error: {exc}"
    return (
        f"Generated image {image['id']} ({image['width']}x{image['height']}, "
        f"{image['backend']}) at {image['url']}\n"
        f"Prompt: {image['prompt']}\nSeed: {image['seed']}"
    )


TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Generate an image locally with the configured ComfyUI or "
        "stable-diffusion.cpp backend. Returns an image id and URL."
    ),
    "parameters": {
        "prompt": {"type": "string", "description": "Positive image prompt"},
        "negative_prompt": {
            "type": "string",
            "description": "Things to avoid in the image",
            "required": False,
        },
        "width": {
            "type": "integer",
            "description": "Image width (default 512, max 1024)",
            "default": 512,
        },
        "height": {
            "type": "integer",
            "description": "Image height (default 512, max 1024)",
            "default": 512,
        },
        "steps": {
            "type": "integer",
            "description": "Diffusion steps (default 20)",
            "default": 20,
        },
        "seed": {
            "type": "integer",
            "description": "Optional deterministic seed",
            "required": False,
        },
    },
    "tier": 2,
    "requires_approval": True,
    "parallel_safe": False,
    "idempotent": False,
}
