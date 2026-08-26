from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


@lru_cache
def load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt(name: str, **kwargs: str) -> str:
    text = load_prompt(name)
    for key, value in kwargs.items():
        text = text.replace("{" + key + "}", value)
    return text
