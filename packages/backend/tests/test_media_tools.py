"""Multimodal tool registration and path checks: OCR, audio, video."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_media_tools_are_registered() -> None:
    from palimind.llm.mixture_of_expert.tools import get_tool_names

    names = set(get_tool_names())
    assert {"image_info", "image_ocr", "image_caption", "audio_transcribe", "video_frames"} <= names


def test_image_info_reads_local_image(tmp_path: Path) -> None:
    from PIL import Image

    from palimind.llm.mixture_of_expert import tools as t

    image_path = tmp_path / "pixel.png"
    Image.new("RGB", (12, 8), "red").save(image_path)
    t.set_tool_context(tmp_path)
    result = json.loads(t.call_tool("image_info", path="pixel.png"))
    assert result["width"] == 12
    assert result["height"] == 8
    assert result["format"] == "PNG"


def test_image_ocr_plumbing(monkeypatch, tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as t

    (tmp_path / "scan.png").write_bytes(b"not-really-an-image")
    monkeypatch.setattr(
        "palimind.ingestion.ocr.extract_text_from_image",
        lambda _bytes: "Invoice total 42",
    )
    t.set_tool_context(tmp_path)
    assert "Invoice total 42" in t.call_tool("image_ocr", path="scan.png")


def test_audio_transcribe_plumbing(monkeypatch, tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as t

    (tmp_path / "note.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(
        "palimind.audio.stt.transcribe_wav_bytes",
        lambda _bytes: "Remember the milk",
    )
    t.set_tool_context(tmp_path)
    assert "Remember the milk" in t.call_tool("audio_transcribe", path="note.wav")


def test_video_frames_extracts_frames(tmp_path: Path) -> None:
    from palimind.llm.mixture_of_expert import tools as t

    video = tmp_path / "clip.mp4"
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=64x64:rate=10",
            str(video),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0 or not video.is_file():
        import pytest

        pytest.skip("ffmpeg could not generate the test video")
    t.set_tool_context(tmp_path)
    payload = json.loads(t.call_tool("video_frames", path="clip.mp4", count=2))
    assert payload["duration"] > 0
    assert len(payload["frames"]) == 2
    assert all(Path(frame["path"]).is_file() for frame in payload["frames"])
