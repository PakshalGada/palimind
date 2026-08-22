from __future__ import annotations

from pathlib import Path
from typing import Any

# Playwright is optional: if it is not installed the tool still registers
# but returns a clear error when called instead of crashing the registry.
try:
    import playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


def _playwright_fetch(url: str, max_chars: int) -> tuple[str, str, str | None]:
    """Headless browser fetch; returns (text, title, screenshot_path)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = page.title()
            text = page.inner_text("body")[:max_chars]
            screenshot_path = None
            if _take_screenshot():
                from core.llm.mixture_of_expert.tools import _get_context

                ctx = _get_context()
                root: Path | None = ctx.get("root")
                if root is not None:
                    shot_dir = root / ".palimind" / "screenshots"
                    shot_dir.mkdir(parents=True, exist_ok=True)
                    screenshot_path = str(shot_dir / f"browse_{_stamp()}.png")
                    page.screenshot(path=screenshot_path)
            return text, title, screenshot_path
        finally:
            browser.close()


def _take_screenshot() -> bool:
    from core.llm.mixture_of_expert.tools import _get_execution_context

    return bool(_get_execution_context().get("browse_screenshot", False))


def _stamp() -> str:
    import time

    return time.strftime("%Y%m%d_%H%M%S")


def browse_url(url: str, max_chars: int = 8000, screenshot: bool = False) -> str:
    """Playwright-based headless browser fetch of a URL. Returns page text
    content, title and optionally a screenshot path."""
    if not _PLAYWRIGHT_AVAILABLE:
        return (
            "Error: Playwright is not installed. Install it with "
            "`pip install playwright && playwright install chromium` to use "
            "the browse_url tool."
        )
    if not str(url).startswith(("http://", "https://")):
        return "Error: url must be an http(s) URL"

    from core.llm.mixture_of_expert.tools import set_execution_context

    set_execution_context(browse_screenshot=bool(screenshot))

    try:
        text, title, shot = _playwright_fetch(str(url), int(max_chars))
    except Exception as e:
        return f"Error browsing URL: {e}"
    finally:
        set_execution_context(browse_screenshot=False)

    if not text.strip():
        text = "(page rendered no text)"
    result = f"Title: {title}\n\n{text}"
    if shot:
        result += f"\n\nScreenshot saved to: {shot}"
    return result


# registry metadata for the main TOOL_REGISTRY
TOOL_DEFINITION: dict[str, Any] = {
    "description": (
        "Fetch a URL with a Playwright headless browser. Returns the rendered "
        "page text, title and optionally a screenshot path."
    ),
    "parameters": {
        "url": "The full URL to browse",
        "max_chars": "Optional: maximum characters of page text (default 8000)",
        "screenshot": "Optional: save a screenshot (true/false)",
    },
    "tier": 2,
    "requires_approval": True,
}
