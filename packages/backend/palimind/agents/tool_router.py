"""Select a small, relevant set of tools for each agent step.

With 50+ registered tools, sending every JSON schema to a local model costs
thousands of tokens and makes tool selection worse. This module keeps the full
allowlist enforced by the runtime, but narrows *what the model sees* to the
tools most likely to be useful for the current task.

The scoring is deliberately deterministic and dependency-free: token overlap
between the task and each tool's name/description, explicit mentions, and a
small set of always-available core tools. An embedding-based reranker can be
layered on later without changing the call sites.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "why",
    "can",
    "will",
    "would",
    "should",
    "could",
    "please",
    "use",
    "using",
    "run",
    "make",
    "need",
    "want",
    "give",
    "find",
    "get",
    "all",
    "any",
    "some",
    "your",
    "our",
    "you",
}

# Core tools that should almost always be visible. They are cheap and cover
# discovery, reading, memory, and delegation.
_CORE_TOOLS = (
    "tool_search",
    "todo_write",
    "ask_user",
    "read_file",
    "list_files",
    "grep_files",
    "document_search",
    "memory_search",
    "web_search",
    "fetch_url",
    "summarize",
    "delegate",
)

# Tool families let a task mentioning "test" or "chart" pull in related tools
# even when the description does not share the exact word.
_DESKTOP_FAMILY = (
    "desktop_status",
    "desktop_apps",
    "desktop_snapshot",
    "desktop_find",
    "desktop_wait",
    "desktop_act",
    "desktop_screenshot",
    "desktop_launch",
    "desktop_browser",
)
_DESKTOP_HINTS = {
    "desktop",
    "screen",
    "window",
    "click",
    "type",
    "typing",
    "keyboard",
    "mouse",
    "screenshot",
    "app",
    "application",
    "browser",
    "brave",
    "chrome",
    "chromium",
    "firefox",
    "edge",
    "vivaldi",
    "opera",
    "youtube",
    "netflix",
    "spotify",
    "movie",
    "video",
    "play",
    "calculator",
    "gedit",
    "nautilus",
    "settings",
}
_FAMILY_HINTS: dict[str, tuple[str, ...]] = {
    "code": ("apply_patch", "edit_file", "repo_map", "code_search", "run_tests", "git_diff"),
    "test": ("run_tests", "run_python", "grep_files"),
    "git": ("git_status", "git_diff", "git_log", "git_show", "git_blame"),
    "data": ("csv_query", "sqlite_query", "duckdb_query", "dataframe_query", "chart_generate"),
    "chart": ("chart_generate", "dataframe_query", "csv_query"),
    "pdf": ("pdf_read", "pdf_extract", "document_search"),
    "image": ("image_info", "image_ocr", "image_caption"),
    "audio": ("audio_transcribe",),
    "video": ("video_frames", "audio_transcribe", *_DESKTOP_FAMILY),
    "email": ("read_email", "send_email"),
    "calendar": ("calendar_ics",),
    "browser": (
        "browser_open",
        "browser_snapshot",
        "browser_extract",
        "browse_url",
        *_DESKTOP_FAMILY,
    ),
    "web": ("web_search", "fetch_url", "browse_url", "web_crawl"),
    "research": ("web_search", "fetch_url", "arxiv_search", "semantic_scholar_search"),
    "arxiv": ("arxiv_search", "semantic_scholar_search", "openalex_search", "crossref_search"),
    "paper": ("arxiv_search", "semantic_scholar_search", "openalex_search", "pubmed_search"),
    "sql": ("sqlite_query", "duckdb_query", "sqlite_schema"),
    "spreadsheet": ("xlsx_read", "xlsx_write", "csv_query", "dataframe_query"),
    "desktop": _DESKTOP_FAMILY,
    "play": _DESKTOP_FAMILY,
    "application": _DESKTOP_FAMILY,
    "app": _DESKTOP_FAMILY,
    "screen": _DESKTOP_FAMILY,
    "window": _DESKTOP_FAMILY,
    "click": _DESKTOP_FAMILY,
    "mouse": _DESKTOP_FAMILY,
    "keyboard": _DESKTOP_FAMILY,
    "screenshot": _DESKTOP_FAMILY,
    "brave": _DESKTOP_FAMILY,
    "chrome": _DESKTOP_FAMILY,
    "chromium": _DESKTOP_FAMILY,
    "firefox": _DESKTOP_FAMILY,
    "edge": _DESKTOP_FAMILY,
    "vivaldi": _DESKTOP_FAMILY,
    "opera": _DESKTOP_FAMILY,
    "youtube": _DESKTOP_FAMILY,
    "netflix": _DESKTOP_FAMILY,
    "spotify": _DESKTOP_FAMILY,
    "movie": _DESKTOP_FAMILY,
    "mcp": ("mcp__",),
}


def is_desktop_task(task: str) -> bool:
    """Whether a task is likely to need desktop/browser control.

    Used only to decide which tools to pin; it never grants a capability. An
    agent without desktop permissions still cannot call the tools even if they
    are named here.
    """

    text = str(task or "").lower()
    tokens = _tokens(text)
    if tokens & _DESKTOP_HINTS:
        return True
    # Multi-word app/page phrases that the tokenizer splits or that are too
    # generic to list as single tokens.
    return any(
        phrase in text
        for phrase in (
            "file manager",
            "desktop app",
            "open the app",
            "switch to",
            "on the screen",
        )
    )


def _tokens(text: str) -> set[str]:
    return {
        w.lower()
        for w in _WORD_RE.findall(str(text or ""))
        if len(w) > 2 and w.lower() not in _STOPWORDS
    }


def _tool_text(name: str, info: dict) -> str:
    params = info.get("parameters") or {}
    if isinstance(params, dict):
        param_names = " ".join(str(k) for k in params)
    else:
        param_names = ""
    return f"{name} {info.get('description', '')} {param_names}"


def score_tools(
    task: str, available: Iterable[str], registry: dict[str, dict]
) -> list[tuple[str, int]]:
    """Return ``(tool_name, score)`` pairs sorted by relevance."""
    task_tokens = _tokens(task)
    lowered = str(task or "").lower()
    scored: list[tuple[str, int]] = []
    for name in available:
        info = registry.get(name)
        if not info:
            continue
        score = len(task_tokens & _tokens(_tool_text(name, info)))
        # Explicit mentions are the strongest signal.
        if name.lower() in lowered:
            score += 12
        # Family hints ("test", "chart", "git", ...) provide a small boost.
        for hint, family in _FAMILY_HINTS.items():
            if hint in task_tokens:
                if name in family or any(name.startswith(prefix) for prefix in family):
                    score += 4
        if name in _CORE_TOOLS:
            score += 1
        scored.append((name, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def select_tools(
    task: str,
    available: Iterable[str],
    registry: dict[str, dict],
    *,
    top_k: int = 12,
    pinned: Iterable[str] | None = None,
    include_core: bool = True,
) -> list[str]:
    """Pick at most *top_k* tools for the model's tool schema.

    ``pinned`` tools are always included. When *include_core* is true, the
    core read/discovery tools are included when they are in *available*.
    """
    names = [str(n) for n in available]
    if not names:
        return []
    limit = max(1, int(top_k or 12))
    selected: list[str] = []

    def _add(name: str) -> None:
        if name in names and name not in selected:
            selected.append(name)

    for name in pinned or ():
        _add(name)
    if include_core:
        for name in _CORE_TOOLS:
            _add(name)

    for name, _score in score_tools(task, names, registry):
        if len(selected) >= limit:
            break
        _add(name)

    # Never return an empty tool set when tools are available.
    if not selected:
        selected = names[:limit]
    return selected[:limit]
