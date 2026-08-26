"""Video ingestion: extract audio with ffmpeg, transcribe with local Whisper,
and produce timestamped transcript chunks.

Everything runs offline:
- ffmpeg (system binary) extracts mono 16 kHz WAV audio
- faster-whisper (CTranslate2, CPU/int8) produces per-segment timestamps
- Segments are grouped into ~chunk_size character chunks aligned to
  segment boundaries; each chunk keeps its media_start_ts / media_end_ts.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_ffmpeg_checked = False
_whisper_models: dict[str, object] = {}


def ffmpeg_available() -> bool:
    global _ffmpeg_checked
    if not _ffmpeg_checked:
        _ffmpeg_checked = True
        if shutil.which("ffmpeg") is None:
            raise RuntimeError(
                "ffmpeg not found on PATH. Install it to enable video indexing "
                "(e.g. 'sudo pacman -S ffmpeg' or 'sudo apt install ffmpeg')."
            )
    return True


def _get_whisper(model_name: str):
    if model_name not in _whisper_models:
        from faster_whisper import WhisperModel

        logger.info(f"Loading whisper model '{model_name}' for video transcription")
        _whisper_models[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _whisper_models[model_name]


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


def extract_audio(video_path: Path) -> Path:
    """Extract mono 16 kHz WAV audio from *video_path* into a temp file."""
    ffmpeg_available()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-vn",  # drop video
        "-ac",
        "1",  # mono
        "-ar",
        "16000",  # whisper-native sample rate
        "-loglevel",
        "error",
        tmp.name,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:500]}")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg audio extraction timed out for {video_path}") from e
    return Path(tmp.name)


def transcribe_audio(
    audio_path: Path,
    model_name: str = "base",
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Transcribe *audio_path*, returning timestamped segments."""
    model = _get_whisper(model_name)
    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language=language or None,
        vad_filter=True,
    )
    segments: list[TranscriptSegment] = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append(
                TranscriptSegment(start=float(seg.start), end=float(seg.end), text=text)
            )
    return segments


def group_segments_into_chunks(
    segments: list[TranscriptSegment],
    *,
    chunk_chars: int = 800,
    max_chunk_seconds: float = 90.0,
) -> list[TranscriptSegment]:
    """Merge consecutive segments into chunks of ~chunk_chars characters.

    Chunk boundaries align to segment boundaries so timestamps stay exact.
    """
    if not segments:
        return []
    chunks: list[TranscriptSegment] = []
    cur_texts: list[str] = []
    cur_start = segments[0].start

    def _flush(end_ts: float):
        text = " ".join(t.strip() for t in cur_texts if t.strip())
        if text:
            chunks.append(TranscriptSegment(start=cur_start, end=end_ts, text=text))
        cur_texts.clear()

    for seg in segments:
        cur_texts.append(seg.text)
        joined_len = sum(len(t) + 1 for t in cur_texts)
        duration = seg.end - cur_start
        if joined_len >= chunk_chars or duration >= max_chunk_seconds:
            _flush(seg.end)
            cur_start = seg.end
    if cur_texts:
        _flush(segments[-1].end)
    return chunks


def parse_video(
    video_path: Path,
    *,
    whisper_model: str = "base",
    chunk_chars: int = 800,
    max_chunk_seconds: float = 90.0,
    language: str | None = None,
) -> tuple[list[TranscriptSegment], list[TranscriptSegment]]:
    """Full pipeline: audio extraction → transcription → chunk grouping.

    Returns ``(chunks, raw_segments)``.
    Raises RuntimeError on ffmpeg failure.
    """
    audio = extract_audio(video_path)
    try:
        segments = transcribe_audio(audio, model_name=whisper_model, language=language)
    finally:
        try:
            audio.unlink(missing_ok=True)
        except OSError:
            pass
    chunks = group_segments_into_chunks(
        segments,
        chunk_chars=chunk_chars,
        max_chunk_seconds=max_chunk_seconds,
    )
    return chunks, segments
