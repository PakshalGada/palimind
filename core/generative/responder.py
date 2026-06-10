from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterator

import httpx

from core.exceptions import ImageEncodeError, ResponseError


def encode_image(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise ImageEncodeError(f"Image not found: {image_path}")
    try:
        return base64.b64encode(path.read_bytes()).decode("utf-8")
    except OSError as e:
        raise ImageEncodeError(f"Failed to encode image {image_path}: {e}") from e


def generate_response_stream(
    query: str,
    context: str,
    image_paths: list[str],
    ollama_url: str,
    chat_model: str,
    system_prompt: str,
    history: list[dict] | None = None,
    is_chat_only: bool = False,
) -> Iterator[str]:
    """Yield response tokens from Ollama."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if history:
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})

    if is_chat_only:
        user_content = query
    elif context and context.strip():
        user_content = (
            "Context information is below:\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n\n"
            "Given the context information and not prior knowledge, answer the query.\n"
            f"Query: {query}\n"
            "Answer:"
        )
    else:
        user_content = (
            "No relevant document context was found in the workspace.\n"
            "Answer the query based on your general knowledge and the system instructions. If appropriate, note that you are answering from general knowledge as no local context was found.\n"
            f"Query: {query}\n"
            "Answer:"
        )
    user_message: dict = {"role": "user", "content": user_content}

    images = []
    for path in image_paths:
        if Path(path).exists():
            images.append(encode_image(path))
    if images:
        user_message["images"] = images

    messages.append(user_message)
    url = f"{ollama_url.rstrip('/')}/api/chat"
    payload = {"model": chat_model, "messages": messages, "stream": True}

    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)) as client:
            with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    content = data.get("message", {}).get("content")
                    if content:
                        yield content
    except httpx.TimeoutException as e:
        raise ResponseError(f"Response generation timed out: {e}") from e
    except httpx.HTTPError as e:
        raise ResponseError(f"Failed to generate response: {e}") from e
    except json.JSONDecodeError as e:
        raise ResponseError(f"Invalid response from Ollama: {e}") from e


def generate_response(stream: Iterator[str]) -> str:
    """Collect a token stream into a single answer string."""
    return "".join(stream)
