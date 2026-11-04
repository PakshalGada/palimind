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


_WHISPER_RATE = 16000
_NOT_WAV = object()


def _decode_wav(wav_bytes: bytes):
    """Decode PCM WAV bytes to 16 kHz mono float32 for Whisper.

    Returns ``_NOT_WAV`` when the bytes are not a PCM WAV file. Decoding here
    (instead of handing a file object to faster-whisper) avoids its PyAV
    path, which breaks on PyAV >= 15 (``open() got an unexpected keyword
    argument 'metadata_errors'``) and failed every dictation. The UI records
    at the device rate (44.1/48 kHz), so resample to Whisper's 16 kHz.
    """
    import wave

    import numpy as np

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError):
        return _NOT_WAV
    if width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        return _NOT_WAV
    if channels > 1:
        usable = len(audio) - len(audio) % channels
        audio = audio[:usable].reshape(-1, channels).mean(axis=1)
    if audio.size and rate and rate != _WHISPER_RATE:
        n_out = int(round(audio.size * _WHISPER_RATE / rate))
        if n_out <= 0:
            return np.zeros(0, dtype=np.float32)
        x_old = np.arange(audio.size, dtype=np.float64) / rate
        x_new = np.arange(n_out, dtype=np.float64) / _WHISPER_RATE
        audio = np.interp(x_new, x_old, audio)
    return np.ascontiguousarray(audio, dtype=np.float32)


def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    """Transcribe in-memory WAV bytes into text."""
    if not wav_bytes:
        return ""
    audio = _decode_wav(wav_bytes)
    if audio is _NOT_WAV:
        audio = io.BytesIO(wav_bytes)  # other containers: let faster-whisper decode
    elif audio.size == 0:
        # Header-only recording (mic produced no samples): nothing to say,
        # and Whisper errors on empty input.
        return ""
    model = get_model()
    segments, info = model.transcribe(audio, beam_size=5)
    text = "".join(segment.text for segment in segments)
    return text.strip()
