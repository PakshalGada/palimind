"""Local multimodal tools: image info/OCR/caption, audio transcription, video frames."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _p(
    *,
    type: str = "string",
    description: str,
    required: bool = True,
    default: Any = None,
    enum: tuple[str, ...] = (),
) -> dict[str, Any]:
    item: dict[str, Any] = {"type": type, "description": description, "required": required}
    if default is not None:
        item["default"] = default
    if enum:
        item["enum"] = list(enum)
    return item


def _resolve(path: str, *, write: bool = False) -> Path | None:
    from palimind.llm.mixture_of_expert.tools import _resolve_in_workspace

    return _resolve_in_workspace(str(path), write=write)


def image_info(path: str) -> str:
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: image not found: {path}"
    try:
        from PIL import Image

        with Image.open(target) as image:
            return json.dumps(
                {
                    "path": str(target),
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                }
            )
    except Exception as exc:  # noqa: BLE001
        return f"Error reading image: {exc}"


def image_ocr(path: str) -> str:
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: image not found: {path}"
    try:
        from palimind.ingestion.ocr import extract_text_from_image

        text = extract_text_from_image(target.read_bytes())
        return text.strip() or "No text detected."
    except Exception as exc:  # noqa: BLE001
        return f"Error running OCR: {exc}"


def image_caption(path: str) -> str:
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: image not found: {path}"
    try:
        from palimind import api_server as server
        from palimind.ingestion.image_parser import caption_image

        config = server._global_chat_config()
        return caption_image(
            target,
            str(config.get("ollama_base_url") or "http://localhost:11434"),
            str(config.get("vision_model") or "llava"),
        )
    except Exception as exc:  # noqa: BLE001
        return f"Error captioning image: {exc}"


def audio_transcribe(path: str) -> str:
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: audio file not found: {path}"
    try:
        from palimind.audio.stt import transcribe_wav_bytes

        text = transcribe_wav_bytes(target.read_bytes())
        return text.strip() or "No speech detected."
    except Exception as exc:  # noqa: BLE001
        return f"Error transcribing audio: {exc}"


def video_frames(path: str, count: int = 4) -> str:
    target = _resolve(path)
    if target is None or not target.is_file():
        return f"Error: video file not found: {path}"
    count = max(1, min(int(count or 4), 12))
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if probe.returncode != 0:
            return f"Error reading video duration: {probe.stderr.strip()[:300]}"
        duration = float(probe.stdout.strip() or 0)
        if duration <= 0:
            return "Error: video has no readable duration"
        from palimind.security.tokens import palimind_home

        out_dir = Path(tempfile.mkdtemp(prefix="palimind-frames-", dir=str(palimind_home())))
        frames: list[dict[str, Any]] = []
        for index in range(count):
            timestamp = duration * (index + 0.5) / count
            frame_path = out_dir / f"frame-{index + 1}.png"
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-y",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(target),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and frame_path.is_file():
                frames.append({"timestamp": round(timestamp, 3), "path": str(frame_path)})
        if not frames:
            return "Error: no frames could be extracted"
        return json.dumps({"duration": round(duration, 3), "frames": frames})
    except FileNotFoundError:
        return "Error: ffmpeg/ffprobe are not installed"
    except Exception as exc:  # noqa: BLE001
        return f"Error extracting video frames: {exc}"


TOOLS: dict[str, dict[str, Any]] = {
    "image_info": {
        "fn": image_info,
        "description": "Read image dimensions, format and color mode.",
        "parameters": {"path": _p(description="Image file path")},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "image_ocr": {
        "fn": image_ocr,
        "description": "Extract text from an image with local OCR.",
        "parameters": {"path": _p(description="Image file path")},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "image_caption": {
        "fn": image_caption,
        "description": "Caption an image with the configured local vision model.",
        "parameters": {"path": _p(description="Image file path")},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "audio_transcribe": {
        "fn": audio_transcribe,
        "description": "Transcribe an audio file with local Whisper.",
        "parameters": {"path": _p(description="Audio file path")},
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": True,
    },
    "video_frames": {
        "fn": video_frames,
        "description": "Extract evenly spaced frames from a video with ffmpeg.",
        "parameters": {
            "path": _p(description="Video file path"),
            "count": _p(type="integer", description="Number of frames", required=False, default=4),
        },
        "tier": 1,
        "requires_approval": False,
        "parallel_safe": True,
        "idempotent": False,
    },
}
