"""Data models for the hotkey system."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class HotkeyConfig:
    """Configuration for hotkey listener."""
    hotkey_combo: str = "<ctrl>+<alt>+<shift>+<space>"  # Default hotkey combination
    api_base_url: str = "http://localhost:8000"  # FastAPI server URL


@dataclass
class CapturedText:
    """Text captured from clipboard."""
    content: str
    timestamp: float  # Unix timestamp


@dataclass
class FieldInfo:
    """Information about a Field."""
    name: str
    path: str  # Full path to field directory
    is_active: bool = False


@dataclass
class HotkeyEvent:
    """Event triggered by hotkey press."""
    selected_text: str
    selected_field: Optional[FieldInfo] = None
