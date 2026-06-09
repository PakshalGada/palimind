import io
from pathlib import Path
from faster_whisper import WhisperModel

_model = None

def get_model():
    global _model
    if _model is None:
        # Load tiny model offline. Cache under user home directory.
        # ctranslate2 tiny runs fast even on low-end CPUs
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

def transcribe_wav_bytes(wav_bytes: bytes) -> str:
    """Transcribe in-memory WAV bytes into text."""
    model = get_model()
    audio_file = io.BytesIO(wav_bytes)
    segments, info = model.transcribe(audio_file, beam_size=5)
    text = "".join(segment.text for segment in segments)
    return text.strip()
