"""Optional local image generation (ComfyUI or stable-diffusion.cpp).

Nothing is downloaded or started automatically. Set ``PALIMIND_IMAGE_BACKEND``
to ``comfyui`` or ``sdcpp`` to enable the feature. Generated PNGs are stored
under ``~/.palimind/images`` and indexed in the state database as image
artifacts, so the API and agent tools can hand back a stable id/URL.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from palimind.exceptions import ImageGenerationError
from palimind.security.tokens import palimind_home
from palimind.settings import (
    COMFYUI_CHECKPOINT,
    COMFYUI_URL,
    IMAGE_BACKEND,
    IMAGE_MAX_SIDE,
    IMAGE_TIMEOUT,
    SDCPP_BINARY,
    SDCPP_MODEL,
)
from palimind.storage import state_store

IMAGE_NS = "image_artifacts"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def images_dir() -> Path:
    path = palimind_home() / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def availability(backend: str | None = None) -> dict[str, Any]:
    """Return whether a local image backend is configured and reachable."""
    chosen = str(backend or IMAGE_BACKEND or "off").lower()
    if chosen in ("off", "none", "disabled", ""):
        return {
            "available": False,
            "backend": "off",
            "reason": "Image generation is disabled. Set PALIMIND_IMAGE_BACKEND.",
        }
    if chosen == "comfyui":
        url = COMFYUI_URL.rstrip("/")
        try:
            resp = httpx.get(f"{url}/system_stats", timeout=3.0)
            if resp.status_code < 400:
                return {
                    "available": True,
                    "backend": "comfyui",
                    "url": url,
                    "checkpoint": COMFYUI_CHECKPOINT,
                    "reason": "",
                }
            return {
                "available": False,
                "backend": "comfyui",
                "url": url,
                "reason": f"ComfyUI returned HTTP {resp.status_code}",
            }
        except Exception as exc:
            return {
                "available": False,
                "backend": "comfyui",
                "url": url,
                "reason": f"ComfyUI is not reachable: {exc}",
            }
    if chosen in ("sdcpp", "stable-diffusion.cpp", "stable_diffusion_cpp"):
        binary = SDCPP_BINARY
        resolved = shutil.which(binary) or (binary if Path(binary).is_file() else "")
        return {
            "available": bool(resolved),
            "backend": "sdcpp",
            "binary": resolved or binary,
            "model": SDCPP_MODEL,
            "reason": "" if resolved else f"stable-diffusion.cpp binary not found: {binary}",
        }
    return {
        "available": False,
        "backend": chosen,
        "reason": f"Unknown image backend: {chosen}",
    }


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(int(value), hi))


def _normalise(
    prompt: str,
    width: int,
    height: int,
    steps: int,
    seed: int | None,
) -> tuple[str, int, int, int, int]:
    text = str(prompt or "").strip()
    if not text:
        raise ImageGenerationError("prompt is required")
    max_side = max(256, int(IMAGE_MAX_SIDE or 1024))
    width = _clamp(width or 512, 64, max_side)
    height = _clamp(height or 512, 64, max_side)
    # Most diffusion backends expect multiples of 8.
    width -= width % 8
    height -= height % 8
    steps = _clamp(steps or 20, 1, 100)
    seed = int(seed) if seed is not None else int(time.time()) & 0x7FFFFFFF
    return text[:4000], width, height, steps, seed


def _generate_comfyui(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
) -> bytes:
    if not COMFYUI_CHECKPOINT:
        raise ImageGenerationError(
            "PALIMIND_COMFYUI_CHECKPOINT is not set; configure a checkpoint name."
        )
    workflow = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": COMFYUI_CHECKPOINT},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "palimind", "images": ["8", 0]},
        },
    }
    base = COMFYUI_URL.rstrip("/")
    try:
        with httpx.Client(timeout=IMAGE_TIMEOUT) as client:
            queued = client.post(
                f"{base}/prompt",
                json={"prompt": workflow, "client_id": f"palimind-{uuid.uuid4().hex}"},
            )
            queued.raise_for_status()
            prompt_id = str((queued.json() or {}).get("prompt_id") or "")
            if not prompt_id:
                raise ImageGenerationError("ComfyUI did not return a prompt id")
            deadline = time.time() + float(IMAGE_TIMEOUT or 240)
            images: list[dict[str, Any]] = []
            while time.time() < deadline:
                history = client.get(f"{base}/history/{prompt_id}")
                history.raise_for_status()
                data = history.json() or {}
                entry = data.get(prompt_id) if isinstance(data, dict) else None
                if entry:
                    outputs = entry.get("outputs") or {}
                    for output in outputs.values():
                        if isinstance(output, dict):
                            images.extend(output.get("images") or [])
                    if images:
                        break
                time.sleep(1.0)
            if not images:
                raise ImageGenerationError("ComfyUI did not produce an image before timeout")
            image = images[0]
            params = {
                "filename": str(image.get("filename") or ""),
                "subfolder": str(image.get("subfolder") or ""),
                "type": str(image.get("type") or "output"),
            }
            rendered = client.get(f"{base}/view", params=params)
            rendered.raise_for_status()
            return rendered.content
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(f"ComfyUI generation failed: {exc}") from exc


def _generate_sdcpp(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    steps: int,
    seed: int,
) -> bytes:
    binary = shutil.which(SDCPP_BINARY) or SDCPP_BINARY
    if not binary or not Path(binary).is_file():
        raise ImageGenerationError(f"stable-diffusion.cpp binary not found: {SDCPP_BINARY}")
    with tempfile.TemporaryDirectory(prefix="palimind-sd-") as tmp:
        output = Path(tmp) / "image.png"
        cmd = [
            binary,
            "-p",
            prompt,
            "-n",
            negative_prompt,
            "-W",
            str(width),
            "-H",
            str(height),
            "--steps",
            str(steps),
            "--seed",
            str(seed),
            "-o",
            str(output),
        ]
        if SDCPP_MODEL:
            cmd.extend(["-m", SDCPP_MODEL])
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=float(IMAGE_TIMEOUT or 240),
                check=False,
            )
        except FileNotFoundError as exc:
            raise ImageGenerationError(f"sd.cpp binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise ImageGenerationError("stable-diffusion.cpp timed out") from exc
        if proc.returncode != 0 or not output.is_file():
            detail = (proc.stderr or proc.stdout or "")[-800:]
            raise ImageGenerationError(f"stable-diffusion.cpp failed: {detail}")
        return output.read_bytes()


def generate_image(
    prompt: str,
    *,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    seed: int | None = None,
    backend: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Generate a PNG with the configured local backend.

    Returns ``(png_bytes, metadata)``. Raises :class:`ImageGenerationError` when
    the backend is disabled/unavailable or produces no image.
    """
    prompt, width, height, steps, seed = _normalise(prompt, width, height, steps, seed)
    chosen = str(backend or IMAGE_BACKEND or "off").lower()
    status = availability(chosen)
    if not status.get("available"):
        raise ImageGenerationError(str(status.get("reason") or "image backend unavailable"))
    if chosen == "comfyui" or (chosen == "" and status.get("backend") == "comfyui"):
        png = _generate_comfyui(prompt, negative_prompt, width, height, steps, seed)
    elif chosen in ("sdcpp", "stable-diffusion.cpp", "stable_diffusion_cpp"):
        png = _generate_sdcpp(prompt, negative_prompt, width, height, steps, seed)
    else:
        raise ImageGenerationError(f"Unsupported image backend: {chosen}")
    if not png or not png.startswith(_PNG_MAGIC):
        raise ImageGenerationError("image backend did not return a valid PNG")
    return png, {
        "prompt": prompt,
        "negative_prompt": str(negative_prompt or "")[:2000],
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "backend": status.get("backend") or chosen,
    }


def save_image(png: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    image_id = uuid.uuid4().hex
    path = images_dir() / f"{image_id}.png"
    path.write_bytes(png)
    record = {
        "id": image_id,
        "title": str(metadata.get("prompt") or "Generated image")[:120],
        "prompt": str(metadata.get("prompt") or "")[:4000],
        "negative_prompt": str(metadata.get("negative_prompt") or "")[:2000],
        "width": int(metadata.get("width") or 0),
        "height": int(metadata.get("height") or 0),
        "steps": int(metadata.get("steps") or 0),
        "seed": int(metadata.get("seed") or 0),
        "backend": str(metadata.get("backend") or ""),
        "path": str(path),
        "size": len(png),
        "mime": "image/png",
        "created_at": time.time(),
        "url": f"/api/images/{image_id}",
    }
    state_store.set_json(IMAGE_NS, image_id, record)
    return public_image(record)


def public_image(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "id",
            "title",
            "prompt",
            "negative_prompt",
            "width",
            "height",
            "steps",
            "seed",
            "backend",
            "size",
            "mime",
            "created_at",
            "url",
        )
    }


def generate_and_save(
    prompt: str,
    *,
    negative_prompt: str = "",
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    seed: int | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    png, metadata = generate_image(
        prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        seed=seed,
        backend=backend,
    )
    return save_image(png, metadata)


def get_image(image_id: str) -> dict[str, Any] | None:
    value = state_store.get_json(IMAGE_NS, str(image_id or ""), default=None)
    return value if isinstance(value, dict) else None


def list_images(limit: int = 100) -> list[dict[str, Any]]:
    items = state_store.list_json(IMAGE_NS, limit=max(1, min(int(limit or 100), 500)))
    items.sort(key=lambda item: float(item.get("created_at", 0) or 0), reverse=True)
    return [public_image(item) for item in items]


def image_bytes(image_id: str) -> bytes | None:
    record = get_image(image_id)
    if record is None:
        return None
    path = Path(str(record.get("path") or ""))
    if not path.is_file():
        return None
    return path.read_bytes()


def delete_image(image_id: str) -> bool:
    record = get_image(image_id)
    if record is None:
        return False
    try:
        Path(str(record.get("path") or "")).unlink(missing_ok=True)
    except OSError:
        pass
    state_store.delete_json(IMAGE_NS, str(image_id))
    return True
