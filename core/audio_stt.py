import io

from core.config import app_cache_dir

_model = None

def get_model():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "Voice transcription requires the optional 'faster-whisper' dependency."
            ) from exc

        model_cache = app_cache_dir() / "models" / "whisper"
        model_cache.mkdir(parents=True, exist_ok=True)

        # ctranslate2 tiny runs fast even on low-end CPUs
        _model = WhisperModel(
            "tiny",
            device="cpu",
            compute_type="int8",
            download_root=str(model_cache),
        )
    return _model

def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    """Transcribe in-memory WAV bytes into text."""
    model = get_model()
    audio_file = io.BytesIO(wav_bytes)
    segments, info = model.transcribe(audio_file, beam_size=5)
    text = "".join(segment.text for segment in segments)
    return text.strip()
