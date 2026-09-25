import io

_model = None
_model_name: str | None = None


def resolve_model_name() -> str:
    """Pick the STT model: user setting (global config) > env > default."""
    import json

    try:
        from palimind.config import GLOBAL_CONFIG_PATH

        if GLOBAL_CONFIG_PATH.exists():
            data = json.loads(GLOBAL_CONFIG_PATH.read_text("utf-8"))
            name = str(data.get("stt_whisper_model") or "").strip()
            if name:
                return name
    except Exception:
        pass
    from palimind.settings import STT_WHISPER_MODEL

    return STT_WHISPER_MODEL or "base.en"


def get_model():
    global _model, _model_name
    name = resolve_model_name()
    if _model is not None and _model_name == name:
        return _model

    from palimind import setup_status

    setup_status.start("stt", f"Preparing speech recognition model ({name})")
    try:
        # Imported lazily so the package (and the API server) can be imported
        # without the optional speech dependency installed.
        from faster_whisper import WhisperModel

        # CPU int8 keeps dictation responsive on low-end machines. The model is
        # cached under the user's home directory after the first download.
        _model = WhisperModel(name, device="cpu", compute_type="int8")
        _model_name = name
    finally:
        setup_status.finish("stt")
    return _model


def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    """Transcribe in-memory WAV bytes into text."""
    model = get_model()
    audio_file = io.BytesIO(wav_bytes)
    segments, info = model.transcribe(audio_file, beam_size=5)
    text = "".join(segment.text for segment in segments)
    return text.strip()
