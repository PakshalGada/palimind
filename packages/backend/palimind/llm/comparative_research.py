"""Multi-model research comparison (Phase 3.4).

Fans a query out to several models, then analyses their answers to surface
consensus, unique insights and contradictions. The similarity analysis is
deterministic and unit-testable; the contradiction pass is an optional LLM
judge that degrades gracefully.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from palimind.generative.citation import tokenize

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]+|[^.!?\n]+$")
_MIN_SENTENCE_TOKENS = 4
_CONSENSUS_THRESHOLD = 0.4


def split_claims(answer: str) -> list[str]:
    claims: list[str] = []
    for match in _SENTENCE_RE.finditer(answer or ""):
        text = match.group(0).strip()
        if len(text) < 30:
            continue
        if text.startswith(("#", "|", ">", "```", "-", "*", "1.")):
            continue
        if len(tokenize(text)) < _MIN_SENTENCE_TOKENS:
            continue
        claims.append(text)
    return claims


def _similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def analyze_comparison(
    answers: dict[str, str],
    *,
    threshold: float = _CONSENSUS_THRESHOLD,
) -> dict[str, Any]:
    """Cluster claims across models into consensus vs. unique insights."""
    models = list(answers.keys())
    claims: list[dict[str, Any]] = []
    for model in models:
        for text in split_claims(answers.get(model, "")):
            claims.append({"model": model, "text": text, "tokens": tokenize(text)})

    # Union-find over claims from different models that are similar enough.
    parent = list(range(len(claims)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if claims[i]["model"] == claims[j]["model"]:
                continue
            if _similarity(claims[i]["tokens"], claims[j]["tokens"]) >= threshold:
                union(i, j)

    clusters: dict[int, list[int]] = {}
    for i in range(len(claims)):
        clusters.setdefault(find(i), []).append(i)

    consensus: list[dict[str, Any]] = []
    unique: dict[str, list[str]] = {model: [] for model in models}

    for members in clusters.values():
        involved_models = sorted({claims[i]["model"] for i in members})
        if len(involved_models) >= 2:
            representative = max(members, key=lambda i: len(claims[i]["text"]))
            consensus.append(
                {
                    "text": claims[representative]["text"],
                    "models": involved_models,
                    "support": round(len(involved_models) / max(1, len(models)), 3),
                }
            )
        else:
            index = members[0]
            unique[claims[index]["model"]].append(claims[index]["text"])

    consensus.sort(key=lambda c: (-c["support"], -len(c["text"])))
    return {
        "models": models,
        "consensus": consensus,
        "unique": unique,
        "claim_counts": {
            model: len(unique[model]) + sum(1 for c in consensus if model in c["models"])
            for model in models
        },
    }


def build_contradiction_prompt(query: str, answers: dict[str, str]) -> str:
    answers_block = "\n\n".join(f"--- {model} ---\n{text}" for model, text in answers.items())
    return (
        "You are a careful fact-checker comparing answers from multiple models to the "
        f'question:\n"{query}"\n\n{answers_block}\n\n'
        "Identify direct contradictions between the models (where two models make "
        "incompatible factual claims). Return ONLY a JSON array of objects with keys "
        '"claim_a", "model_a", "claim_b", "model_b", "explanation". '
        "Return [] if there are no contradictions."
    )


def parse_contradictions(text: str) -> list[dict[str, Any]]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1])
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            out.append(
                {
                    "claim_a": str(item.get("claim_a", ""))[:500],
                    "model_a": str(item.get("model_a", ""))[:80],
                    "claim_b": str(item.get("claim_b", ""))[:500],
                    "model_b": str(item.get("model_b", ""))[:80],
                    "explanation": str(item.get("explanation", ""))[:500],
                }
            )
    return out[:20]


async def find_contradictions(
    query: str,
    answers: dict[str, str],
    *,
    model: str,
    ollama_url: str,
    num_ctx: int = 8192,
) -> list[dict[str, Any]]:
    """Optional LLM pass; returns [] on any failure."""
    from palimind.llm.mixture_of_expert.llm import llm_chat_safe

    prompt = build_contradiction_prompt(query, answers)
    try:
        result = await asyncio.to_thread(
            llm_chat_safe,
            [{"role": "user", "content": prompt}],
            model,
            ollama_url,
            format="json",
            temperature=0.0,
            num_predict=800,
            read_timeout=120.0,
            num_ctx=num_ctx,
            error_prefix="[compare error",
        )
        return parse_contradictions(result.get("content", ""))
    except Exception:
        return []
