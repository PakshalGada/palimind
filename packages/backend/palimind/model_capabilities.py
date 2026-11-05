"""Model capability registry.

Local Ollama installs expose very different models: some support tools, some
are vision models, some are embedding-only, and context windows vary widely.
The rest of the app should ask for a *capability* (``tools``, ``vision``,
``reasoning``, ``embedding``) instead of hard-coding model names.

Capabilities are inferred from a curated table and then refined by Ollama's
``/api/show`` endpoint when it is reachable. Every lookup degrades gracefully:
if Ollama is down, the name-based inference is still returned.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from palimind.opencode.client import proxy_auth_headers

# Capability names used by the app.
CAPABILITIES = ("tools", "vision", "reasoning", "embedding", "code")

# (substring, capabilities, context_window, embedding_dim)
# Order matters: the first matching entry wins for each capability.
_KNOWN: tuple[tuple[str, frozenset[str], int, int], ...] = (
    # Embedding-only models.
    ("nomic-embed-text", frozenset({"embedding"}), 8192, 768),
    ("bge-m3", frozenset({"embedding"}), 8192, 1024),
    ("bge-large", frozenset({"embedding"}), 512, 1024),
    ("mxbai-embed-large", frozenset({"embedding"}), 512, 1024),
    ("all-minilm", frozenset({"embedding"}), 512, 384),
    ("snowflake-arctic-embed", frozenset({"embedding"}), 8192, 1024),
    ("qwen3-embedding", frozenset({"embedding"}), 8192, 1024),
    # Vision models.
    ("llama3.2-vision", frozenset({"vision", "tools"}), 131072, 0),
    ("llama3.2:vision", frozenset({"vision", "tools"}), 131072, 0),
    ("qwen2.5-vl", frozenset({"vision", "tools"}), 131072, 0),
    ("qwen2-vl", frozenset({"vision", "tools"}), 32768, 0),
    ("qwen3-vl", frozenset({"vision", "tools", "reasoning"}), 131072, 0),
    ("minicpm-v", frozenset({"vision"}), 32768, 0),
    ("moondream", frozenset({"vision"}), 8192, 0),
    ("bakllava", frozenset({"vision"}), 8192, 0),
    ("llava", frozenset({"vision"}), 8192, 0),
    ("gemma3", frozenset({"vision", "tools"}), 131072, 0),
    ("phi4-multimodal", frozenset({"vision", "tools"}), 131072, 0),
    ("granite3.2-vision", frozenset({"vision", "tools"}), 131072, 0),
    # Reasoning models.
    ("deepseek-r1", frozenset({"reasoning", "tools"}), 131072, 0),
    ("deepseek-reasoner", frozenset({"reasoning", "tools"}), 131072, 0),
    ("qwen3", frozenset({"reasoning", "tools"}), 131072, 0),
    ("phi4-reasoning", frozenset({"reasoning", "tools"}), 131072, 0),
    ("magistral", frozenset({"reasoning", "tools"}), 131072, 0),
    ("gpt-oss", frozenset({"reasoning", "tools"}), 131072, 0),
    # Code models.
    ("qwen2.5-coder", frozenset({"tools", "code"}), 131072, 0),
    ("qwen3-coder", frozenset({"tools", "code", "reasoning"}), 262144, 0),
    ("deepseek-coder", frozenset({"tools", "code"}), 16384, 0),
    ("codellama", frozenset({"code"}), 16384, 0),
    ("starcoder", frozenset({"code"}), 16384, 0),
    ("devstral", frozenset({"tools", "code"}), 131072, 0),
    # Tool-capable general chat models.
    ("llama3.3", frozenset({"tools"}), 131072, 0),
    ("llama3.1", frozenset({"tools"}), 131072, 0),
    ("llama3.2", frozenset({"tools"}), 131072, 0),
    ("mistral-nemo", frozenset({"tools"}), 131072, 0),
    ("mistral", frozenset({"tools"}), 32768, 0),
    ("command-r", frozenset({"tools"}), 131072, 0),
    ("granite3", frozenset({"tools"}), 131072, 0),
    ("firefunction", frozenset({"tools"}), 32768, 0),
    ("hermes", frozenset({"tools"}), 32768, 0),
    ("qwen2.5", frozenset({"tools"}), 131072, 0),
    ("gemma2", frozenset({"tools"}), 8192, 0),
    ("gemma", frozenset({"tools"}), 8192, 0),
    ("phi4", frozenset({"tools"}), 16384, 0),
    ("phi3", frozenset({"tools"}), 131072, 0),
)

_DEFAULT_CONTEXT = 8192
_cache: dict[tuple[str, str], tuple[float, ModelCapabilities]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 300.0


@dataclass
class ModelCapabilities:
    """What a model can do, in terms the app can route on."""

    model_id: str
    capabilities: list[str] = field(default_factory=list)
    context_window: int = _DEFAULT_CONTEXT
    embedding_dim: int = 0
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    source: str = "inferred"  # inferred | ollama | override
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_tools(self) -> bool:
        return "tools" in self.capabilities

    @property
    def supports_vision(self) -> bool:
        return "vision" in self.capabilities

    @property
    def supports_reasoning(self) -> bool:
        return "reasoning" in self.capabilities

    @property
    def is_embedding(self) -> bool:
        return "embedding" in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "supports_tools": self.supports_tools,
                "supports_vision": self.supports_vision,
                "supports_reasoning": self.supports_reasoning,
                "is_embedding": self.is_embedding,
            }
        )
        return data


def infer_from_name(model_id: str) -> ModelCapabilities:
    """Infer capabilities from a model name without any network call."""
    name = str(model_id or "").strip().lower()
    caps: set[str] = set()
    context = _DEFAULT_CONTEXT
    embed_dim = 0
    family = name.split(":")[0].split("/")[-1]
    for needle, capabilities, ctx, dim in _KNOWN:
        if needle in name:
            caps.update(capabilities)
            context = max(context, ctx)
            if dim:
                embed_dim = dim
            family = needle
            break
    # A model without an embedding/vet signal is assumed to be a chat model.
    if not caps:
        caps = {"tools"} if any(k in name for k in ("instruct", "chat", "latest")) else set()
    return ModelCapabilities(
        model_id=str(model_id or ""),
        capabilities=sorted(caps),
        context_window=context,
        embedding_dim=embed_dim,
        family=family,
    )


def _ollama_show(model_id: str, base_url: str) -> dict[str, Any] | None:
    """Fetch ``/api/show`` for *model_id*; return None when unavailable."""
    if not base_url:
        return None
    try:
        import httpx

        url = f"{base_url.rstrip('/')}/api/show"
        resp = httpx.post(
            url,
            json={"model": model_id},
            timeout=httpx.Timeout(connect=1.0, read=3.0, write=1.0, pool=1.0),
            headers=proxy_auth_headers(url),
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _merge_ollama(caps: ModelCapabilities, data: dict[str, Any]) -> ModelCapabilities:
    model_info = data.get("model_info") or {}
    if not isinstance(model_info, dict):
        model_info = {}
    # Ollama reports capabilities in newer versions.
    reported = data.get("capabilities")
    if isinstance(reported, list) and reported:
        merged = {str(c) for c in reported if c}
        # Keep our extra semantic labels (reasoning/code) but trust Ollama for
        # the hard signals it reports.
        merged.update(c for c in caps.capabilities if c in ("reasoning", "code"))
        caps.capabilities = sorted(merged)
    # Context length lives under a keys like "qwen2.context_length".
    for key, value in model_info.items():
        if str(key).endswith(".context_length") and isinstance(value, int) and value > 0:
            caps.context_window = int(value)
            break
    details = data.get("details") or {}
    if isinstance(details, dict):
        caps.family = str(details.get("family") or caps.family)
        caps.parameter_size = str(details.get("parameter_size") or "")
        caps.quantization = str(details.get("quantization_level") or "")
    caps.source = "ollama"
    caps.raw = data
    return caps


def get_capabilities(
    model_id: str,
    base_url: str = "",
    *,
    use_ollama: bool = True,
    ttl: float = _CACHE_TTL,
) -> ModelCapabilities:
    """Return capabilities for *model_id*, using a short-lived cache."""
    key = (str(model_id or ""), str(base_url or ""))
    now = time.time()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < ttl:
            return cached[1]

    caps = infer_from_name(model_id)
    if use_ollama and base_url:
        data = _ollama_show(model_id, base_url)
        if data:
            caps = _merge_ollama(caps, data)

    with _cache_lock:
        _cache[key] = (now, caps)
    return caps


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def pick_model(
    required: list[str] | tuple[str, ...],
    candidates: list[str],
    base_url: str = "",
) -> str | None:
    """Return the first candidate that has every required capability."""
    needed = {str(c) for c in required if c}
    for model_id in candidates:
        caps = get_capabilities(model_id, base_url)
        if needed.issubset(set(caps.capabilities)):
            return model_id
    return None


def capabilities_for_models(
    models: list[str], base_url: str = "", *, use_ollama: bool = True
) -> list[dict[str, Any]]:
    return [
        get_capabilities(model_id, base_url, use_ollama=use_ollama).to_dict() for model_id in models
    ]
