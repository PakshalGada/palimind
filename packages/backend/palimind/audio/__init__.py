"""Speech-to-text and text-to-speech services."""

from palimind.audio.stt import transcribe_wav_bytes
from palimind.audio.tts import text_to_speech_bytes

__all__ = ["transcribe_wav_bytes", "text_to_speech_bytes"]
