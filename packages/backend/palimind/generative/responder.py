from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx

from palimind.exceptions import ImageEncodeError, ResponseError


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
    on_reasoning: Callable[[str], None] | None = None,
) -> Iterator[str]:
    """Yield response tokens from Ollama.

    ``on_reasoning`` receives chain-of-thought fragments (``reasoning`` field)
    emitted by reasoning models separately from the answer text, so the answer
    stream stays clean and callers can surface the thinking on demand.
    """
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
            "Relevant context from the knowledge base:\n"
            "---------------------\n"
            f"{context}\n"
            "---------------------\n\n"
            "Answer the query using ONLY the retrieved context above.\n"
            "CRITICAL INSTRUCTIONS:\n"
            '1. EXACT TEXT: Quote exact sentences from the context when answering. Use "quote marks" for direct quotes.\n'
            "2. CITE SOURCES: You MUST cite the exact source file using brackets (e.g. [filename]) and year for every claim.\n"
            "3. YEAR COVERAGE: If the query asks about specific years (e.g., 2023, 2024, 2025), check whether context for ALL requested years is present. If information for a specific year is missing, explicitly say: 'No information found for [year] in the retrieved context.'\n"
            "4. COMPARISONS: When comparing across years, present each year's information separately with clear year labels. Note what changed, what stayed the same, and any new or removed statements.\n"
            "5. NO HALLUCINATION: Do not infer, guess, or fabricate content. If the context does not contain enough information to answer fully, say explicitly what is missing.\n"
            '6. SECTION AWARENESS: Pay attention to section headers in the context (e.g., "Item 1A. Risk Factors", "Human Capital") and indicate which section the information comes from.\n'
            "Never fabricate specific numbers, dates, names, or statements that are not in the context.\n"
            f"Query: {query}\n"
            "Answer:"
        )
    else:
        # No context — pass query directly; system prompt handles the fallback.
        user_content = query
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
        with httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
        ) as client:
            with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    message = data.get("message", {}) or {}
                    content = message.get("content")
                    if content:
                        yield content
                    if on_reasoning is not None:
                        reasoning = message.get("reasoning")
                        if reasoning:
                            on_reasoning(reasoning)
    except httpx.TimeoutException as e:
        raise ResponseError(f"Response generation timed out: {e}") from e
    except httpx.HTTPError as e:
        raise ResponseError(f"Failed to generate response: {e}") from e
    except json.JSONDecodeError as e:
        raise ResponseError(f"Invalid response from Ollama: {e}") from e


def generate_response(stream: Iterator[str]) -> str:
    """Collect a token stream into a single answer string."""
    return "".join(stream)
