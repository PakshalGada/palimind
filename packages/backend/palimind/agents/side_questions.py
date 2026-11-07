"""Ephemeral side questions.

A side question is answered from the agent's profile and the end of its chat
with no tools.  It is not written to the conversation, so it cannot pollute the
agent's context or the user's history.
"""

from __future__ import annotations

from typing import Any

MAX_EARLIER = 20
MAX_ANSWER_CHARS = 32_000


def ask(
    definition: Any,
    question: str,
    *,
    earlier: list[dict[str, str]] | None = None,
    working_root: Any = None,
    ollama_url: str = "",
) -> str:
    question = str(question or "").strip()
    if not question:
        raise ValueError("question is required")
    from palimind.agents.chat import read_chat
    from palimind.agents.runtime import _field_models
    from palimind.llm.mixture_of_expert.llm import llm_chat

    chat_model, field_url, light_model = _field_models(working_root)
    model = str(getattr(definition, "model", "") or chat_model or light_model or "")
    base_url = ollama_url or field_url
    try:
        from palimind.opencode.router import resolve_model_url

        base_url = resolve_model_url(model, base_url)
    except Exception:
        pass

    messages: list[dict[str, str]] = []
    instructions = str(
        getattr(definition, "system_prompt", "")
        or getattr(definition, "custom_instructions", "")
        or ""
    )
    if instructions:
        messages.append({"role": "system", "content": instructions})
    history = read_chat(getattr(definition, "id", ""))
    for entry in history[-20:]:
        role = str(entry.get("role") or "user")
        content = str(entry.get("content") or "")
        if content:
            messages.append({"role": "assistant" if role == "agent" else role, "content": content})
    for pair in (earlier or [])[-MAX_EARLIER:]:
        if pair.get("question"):
            messages.append({"role": "user", "content": str(pair["question"])})
        if pair.get("answer"):
            messages.append({"role": "assistant", "content": str(pair["answer"])})
    messages.append({"role": "user", "content": question})

    result = llm_chat(messages, model, base_url)
    answer = str(result.get("content") or "")[:MAX_ANSWER_CHARS]
    return answer
