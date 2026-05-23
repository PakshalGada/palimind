import json

import httpx

from ..prompts import load_prompt, render_prompt

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_CHAT_MODEL = "llama3"


def _build_user_message(
    question: str,
    context_chunks: list[tuple[str, str]],  # [(chunk_text, source_path), ...]
) -> str:
    sections = [
        render_prompt(
            "context_chunk",
            source_path=source_path,
            chunk_text=chunk_text,
        )
        for chunk_text, source_path in context_chunks
    ]
    context_block = "\n\n---\n\n".join(sections)
    return render_prompt(
        "ask_user",
        context=context_block,
        question=question,
    )


def respond(
    question: str,
    context_chunks: list[tuple[str, str]],
    model: str = DEFAULT_CHAT_MODEL,
) -> None:
    """Stream the LLM answer to stdout, token by token."""
    user_message = _build_user_message(question, context_chunks)
    payload = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": load_prompt("system")},
            {"role": "user", "content": user_message},
        ],
    }

    try:
        with httpx.stream(
            "POST",
            f"{OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=120.0,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("message", {}).get("content", "")
                if token:
                    print(token, end="", flush=True)
                if data.get("done"):
                    break
    except httpx.ConnectError:
        raise RuntimeError(
            "Cannot reach Ollama at localhost:11434. "
            "Please start Ollama with `ollama serve` and try again."
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Ollama chat error: {e.response.text}") from e

    print()
