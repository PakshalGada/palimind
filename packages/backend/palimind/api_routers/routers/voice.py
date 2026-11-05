"""Voice transcription, synthesis and the live voice loop.

The live loop is a single SSE request:

``POST /api/voice/chat`` (raw WAV body)
    -> ``vad`` (speech detected?)
    -> ``stream`` (voice stream id)
    -> ``transcript`` (Whisper)
    -> ``token`` (chat answer chunks)
    -> ``audio`` (base64 WAV chunks from Kokoro)
    -> ``done``

A client can barge in by calling ``POST /api/voice/chat/stop`` with the stream
id; the generator stops at the next token/TTS boundary and emits ``cancelled``.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from palimind.audio.stt import transcribe_wav_bytes
from palimind.audio.tts import text_to_speech_bytes

router = APIRouter(prefix="/api/voice", tags=["voice"])

_VOICE_STREAMS: dict[str, threading.Event] = {}
_VOICE_LOCK = threading.Lock()
_VAD_RMS = 0.003
_TTS_CHUNK_CHARS = 160


@router.post("/transcribe")
async def voice_transcribe(request: Request):
    wav_bytes = await request.body()
    if not wav_bytes:
        return {"error": "Empty audio data"}
    try:
        text = await asyncio.to_thread(transcribe_wav_bytes, wav_bytes)
        return {"text": text}
    except Exception:
        return {"error": "Transcription failed"}


@router.post("/synthesize")
async def voice_synthesize(request: Request):
    try:
        data = await request.json()
        text = data.get("text")
        voice = data.get("voice", "af_bella")
        if not text:
            return {"error": "text is required"}
        wav_bytes = await asyncio.to_thread(text_to_speech_bytes, text, voice)
        if not wav_bytes:
            return Response(status_code=500, content="TTS synthesis failed")
        return Response(content=wav_bytes, media_type="audio/wav")
    except Exception:
        return {"error": "TTS synthesis failed"}


def _vad_has_speech(wav_bytes: bytes, threshold: float = _VAD_RMS) -> bool:
    """Cheap energy VAD. Non-WAV input is passed through to Whisper."""
    try:
        from palimind.audio.stt import _NOT_WAV, _decode_wav

        audio = _decode_wav(wav_bytes)
        if audio is _NOT_WAV or not hasattr(audio, "size"):
            return True
        if audio.size == 0:
            return False
        try:
            import numpy as np

            rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float32)))))
        except Exception:
            rms = float((sum(float(x) * float(x) for x in audio) / audio.size) ** 0.5)
        return rms >= float(threshold)
    except Exception:
        return True


async def _stream_answer(
    transcript: str,
    *,
    history: list[dict[str, Any]] | None = None,
    session_id: str = "",
) -> Any:
    """Yield answer tokens from the local chat model."""
    from palimind.config import load_global_config
    from palimind.generative.responder import aiter_stream, generate_response_stream

    config = load_global_config()
    stream = generate_response_stream(
        query=transcript,
        context="",
        image_paths=[],
        ollama_url=str(config.get("ollama_base_url") or "http://localhost:11434"),
        chat_model=str(config.get("chat_model") or "llama3"),
        system_prompt=(
            "You are a helpful local voice assistant. Answer concisely and naturally, "
            "as your response will be spoken aloud."
        ),
        history=history or [],
        is_chat_only=True,
        num_ctx=config.get("num_ctx"),
    )
    async for token in aiter_stream(stream):
        yield token


def _voice_event(event_type: str, **payload: Any) -> str:
    import json

    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


def _register_stream(stream_id: str) -> threading.Event:
    cancel = threading.Event()
    with _VOICE_LOCK:
        _VOICE_STREAMS[stream_id] = cancel
    return cancel


def _unregister_stream(stream_id: str) -> None:
    with _VOICE_LOCK:
        _VOICE_STREAMS.pop(stream_id, None)


@router.post("/chat/stop")
async def stop_voice_chat(stream_id: str = ""):
    """Barge-in: stop an in-flight voice stream at the next safe boundary."""
    with _VOICE_LOCK:
        cancel = _VOICE_STREAMS.get(str(stream_id or ""))
    if cancel is None:
        return {"status": "not_found"}
    cancel.set()
    return {"status": "stopping", "stream_id": stream_id}


@router.post("/chat")
async def voice_chat(
    request: Request,
    session_id: str = "",
    voice: str = "af_bella",
    stream_id: str = "",
    use_vad: bool = True,
    scope: str = "chat",
):
    """Transcribe WAV input, stream a chat answer and synthesize it to audio."""
    wav_bytes = await request.body()
    if not wav_bytes:
        return {"error": "Empty audio data"}
    stream_key = str(stream_id or uuid.uuid4().hex)
    cancel = _register_stream(stream_key)

    root = None
    server: Any = None
    try:
        from palimind import api_server as server_module

        server = server_module
        root = server._chat_root(scope)
    except Exception:
        server = None
        root = None
    try:
        if root is not None and server is not None:
            session_key = await server._resolve_chat_session(root, session_id or None)
        else:
            session_key = session_id
    except Exception:
        session_key = session_id

    async def gen():
        answer = ""
        pending = ""
        history: list[dict[str, Any]] = []
        try:
            yield _voice_event("stream", stream_id=stream_key)
            speech = _vad_has_speech(wav_bytes) if use_vad else True
            yield _voice_event("vad", speech=bool(speech), stream_id=stream_key)
            if not speech:
                yield _voice_event("done", reason="silence", stream_id=stream_key)
                return
            if cancel.is_set():
                yield _voice_event("cancelled", stream_id=stream_key)
                yield _voice_event("done", reason="cancelled", stream_id=stream_key)
                return

            try:
                transcript = await asyncio.to_thread(transcribe_wav_bytes, wav_bytes)
            except Exception as exc:  # noqa: BLE001
                yield _voice_event("error", text=f"Transcription failed: {exc}")
                yield _voice_event("done", stream_id=stream_key)
                return
            transcript = str(transcript or "").strip()
            yield _voice_event("transcript", text=transcript, stream_id=stream_key)
            if not transcript:
                yield _voice_event("done", reason="empty_transcript", stream_id=stream_key)
                return

            if root is not None and session_key:
                try:
                    from palimind.memory.session_store import append_message_to_session

                    await asyncio.to_thread(
                        append_message_to_session, root, session_key, "user", transcript
                    )
                except Exception:
                    pass

            try:
                async for token in _stream_answer(
                    transcript, history=history, session_id=session_key or ""
                ):
                    if cancel.is_set():
                        break
                    text = str(token or "")
                    if not text:
                        continue
                    answer += text
                    pending += text
                    yield _voice_event("token", text=text, stream_id=stream_key)
                    if len(pending) >= _TTS_CHUNK_CHARS or text[-1:] in ".!?\n":
                        wav = await asyncio.to_thread(text_to_speech_bytes, pending.strip(), voice)
                        if wav:
                            yield _voice_event(
                                "audio",
                                audio=base64.b64encode(wav).decode("ascii"),
                                mime="audio/wav",
                                stream_id=stream_key,
                            )
                        pending = ""
                if pending.strip() and not cancel.is_set():
                    wav = await asyncio.to_thread(text_to_speech_bytes, pending.strip(), voice)
                    if wav:
                        yield _voice_event(
                            "audio",
                            audio=base64.b64encode(wav).decode("ascii"),
                            mime="audio/wav",
                            stream_id=stream_key,
                        )
            except Exception as exc:  # noqa: BLE001
                if not answer:
                    yield _voice_event("error", text=f"Chat failed: {exc}")
            finally:
                if root is not None and session_key and answer:
                    try:
                        from palimind.memory.session_store import append_message_to_session

                        await asyncio.to_thread(
                            append_message_to_session,
                            root,
                            session_key,
                            "system",
                            answer,
                        )
                    except Exception:
                        pass
            if cancel.is_set():
                yield _voice_event("cancelled", stream_id=stream_key)
                yield _voice_event("done", reason="cancelled", stream_id=stream_key)
            else:
                yield _voice_event("done", stream_id=stream_key)
        finally:
            _unregister_stream(stream_key)

    return StreamingResponse(gen(), media_type="text/event-stream")
