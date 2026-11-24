"""Chat intelligence flows: critic pass and multi-model council."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from palimind.chat_audit import append_chat_audit, read_chat_audit

router = APIRouter(prefix="/api/chat", tags=["chat"])

_CRITIC_SYSTEM = (
    "You are a rigorous critic. Review the assistant answer for correctness, unsupported "
    "claims, missing evidence, edge cases and clarity. Return Markdown with these sections:\n"
    "## Verdict\nOne paragraph.\n"
    "## Issues\nRanked bullets with severity.\n"
    "## Revised answer\nA corrected, improved answer."
)

_COUNCIL_SYSTEM = (
    "You are a council synthesizer. Several models answered the same question. Merge the "
    "strongest correct points, resolve contradictions explicitly, and return one clear answer. "
    "Do not mention internal model names unless the disagreement matters."
)


def _chat_config() -> dict[str, Any]:
    from palimind import api_server as server

    return server._global_chat_config()


def _model_ids(ollama_url: str) -> list[str]:
    from palimind import api_server as server

    try:
        models = server._fetch_ollama_models_blocking(ollama_url)
    except Exception:
        models = []
    return [str(item.get("model_id") or "") for item in models if item.get("model_id")]


@router.post("/critic")
async def chat_critic(req: Request):
    from fastapi import HTTPException

    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    text = str((body or {}).get("text") or "").strip()
    question = str((body or {}).get("question") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    config = _chat_config()
    ollama_url = str(config.get("ollama_base_url") or "http://localhost:11434")
    model = str(body.get("model") or config.get("chat_model") or "llama3")
    messages = [
        {"role": "system", "content": _CRITIC_SYSTEM},
        {
            "role": "user",
            "content": f"Question:\n{question or '(not provided)'}\n\nAssistant answer:\n{text}",
        },
    ]

    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

    try:
        result = await asyncio.to_thread(
            llm_chat_safe,
            messages,
            model,
            ollama_url,
            error_prefix="[critic error",
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Critic pass failed: {exc}") from exc

    content = str(result.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=502, detail="The local model returned an empty critique")
    append_chat_audit("chat.critic", detail={"model": model, "answer_chars": len(text)})
    return {"critique": content, "model": model}


@router.post("/council")
async def chat_council(req: Request):
    from fastapi import HTTPException

    try:
        body = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    config = _chat_config()
    ollama_url = str(config.get("ollama_base_url") or "http://localhost:11434")
    requested = body.get("models") if isinstance(body.get("models"), list) else []
    models = [str(item).strip() for item in requested if str(item).strip()]
    if not models:
        for key in ("chat_model", "moe_orchestrator_model", "moe_worker_model"):
            value = str(config.get(key) or "").strip()
            if value and value not in models:
                models.append(value)
    if len(models) < 2:
        for value in _model_ids(ollama_url):
            if value and value not in models:
                models.append(value)
            if len(models) >= 3:
                break
    models = models[:3]
    if not models:
        raise HTTPException(status_code=503, detail="No local models are available")

    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

    messages = [
        {
            "role": "system",
            "content": "Answer the user's question carefully, with concrete detail and explicit uncertainty.",
        },
        {"role": "user", "content": text},
    ]

    async def answer_with(model: str) -> dict[str, str]:
        try:
            result = await asyncio.to_thread(
                llm_chat_safe,
                messages,
                model,
                ollama_url,
                error_prefix="[council error",
            )
            return {"model": model, "answer": str(result.get("content") or "").strip()}
        except Exception as exc:  # noqa: BLE001
            return {"model": model, "answer": f"**Error:** {exc}"}

    members = list(await asyncio.gather(*(answer_with(model) for model in models)))
    usable = [member for member in members if member["answer"] and not member["answer"].startswith("**Error:**")]
    if not usable:
        raise HTTPException(status_code=502, detail="Every council member failed to answer")

    synthesis = usable[0]["answer"]
    if len(usable) > 1:
        joined = "\n\n".join(
            f"### Model {index + 1}\n{member['answer']}" for index, member in enumerate(usable)
        )
        synth_messages = [
            {"role": "system", "content": _COUNCIL_SYSTEM},
            {"role": "user", "content": f"Question:\n{text}\n\nAnswers:\n{joined}"},
        ]
        try:
            result = await asyncio.to_thread(
                llm_chat_safe,
                synth_messages,
                usable[0]["model"],
                ollama_url,
                error_prefix="[council synthesis error",
            )
            synthesis = str(result.get("content") or "").strip() or synthesis
        except Exception:
            pass

    append_chat_audit(
        "chat.council",
        detail={"models": models, "usable": len(usable)},
    )
    return {"members": members, "synthesis": synthesis, "models": models}


@router.get("/audit")
async def chat_audit(session_id: str = "", limit: int = 100):
    return {"events": read_chat_audit(limit=limit, session_id=session_id)}
