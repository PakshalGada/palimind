"""Main hotkey manager - orchestrates capture and field selection."""
from __future__ import annotations

import time
import threading
from typing import Callable, Optional

from hotkey.models import HotkeyConfig, HotkeyEvent, FieldInfo
from hotkey.platform_bindings import get_platform_bindings
from hotkey.popup_ui import show_field_selector
from hotkey.integrations import get_capture_processor


class HotkeyManager:
    """
    Manages global hotkey listener and field capture workflow.
    
    Flow:
    1. User presses hotkey (e.g., Ctrl+Shift+E)
    2. Selected text is captured from clipboard
    3. Field selector popup appears
    4. User selects which Field to save to
    5. Callback is invoked with HotkeyEvent
    """

    def __init__(self, config: Optional[HotkeyConfig] = None):
        """
        Initialize hotkey manager.
        
        Args:
            config: HotkeyConfig with hotkey combination and API URL
        """
        self.config = config or HotkeyConfig()
        self.bindings = get_platform_bindings()
        self.processor = get_capture_processor(self.config.api_base_url)
        self.event_callback: Optional[Callable[[HotkeyEvent], None]] = None
        self.is_listening = False
        self._last_capture_time = 0
        self._debounce_ms = 500  # Prevent multiple rapid captures

    def start(self, on_event: Callable[[HotkeyEvent], None]) -> None:
        """
        Start listening for hotkey and capturing text.
        
        Args:
            on_event: Callback function to invoke when text is captured and field selected
        """
        if self.is_listening:
            print("⚠ Hotkey listener already running")
            return

        self.event_callback = on_event
        self.bindings.register_hotkey(self.config.hotkey_combo, self._on_hotkey_pressed)
        self.is_listening = True
        print(f"✓ Hotkey manager started (hotkey: {self.config.hotkey_combo})")

    def stop(self) -> None:
        """Stop listening for hotkey."""
        if not self.is_listening:
            return

        self.bindings.stop_hotkey()
        self.is_listening = False
        print("✓ Hotkey manager stopped")

    def _on_hotkey_pressed(self, sync: bool = False) -> None:
        """Handle hotkey press - capture text then show field selector."""
        # Debounce rapid presses
        now = time.time() * 1000
        if now - self._last_capture_time < self._debounce_ms:
            return
        self._last_capture_time = now

        print("⚡ Hotkey triggered! Capturing text...")

        # 1. Back up current clipboard content
        old_text = self.bindings.get_clipboard_text()

        # 2. Simulate Copy
        self.bindings.simulate_copy()

        # 3. Retrieve the selected text
        captured_text = self.bindings.get_clipboard_text()

        # 4. Restore the backup clipboard
        self.bindings.set_clipboard_text(old_text)

        # Fallback to backup if no selection was captured
        if not captured_text or not captured_text.strip():
            captured_text = old_text

        # Final placeholder if still empty
        if not captured_text or not captured_text.strip():
            captured_text = "[No text captured. Make sure to select text before pressing the hotkey.]"

        self.captured_text = captured_text
        print(f"✓ Text captured ({len(captured_text)} chars)")

        if sync:
            show_field_selector(self.captured_text, self._on_field_selected)
        else:
            # Show field selector in separate thread to avoid blocking pynput
            selector_thread = threading.Thread(
                target=lambda: show_field_selector(self.captured_text, self._on_field_selected), 
                daemon=True
            )
            selector_thread.start()

    def _on_field_selected(self, field: Optional[FieldInfo]) -> None:
        """
        Handle field selection from popup. We already have the captured text.
        
        Args:
            field: Selected FieldInfo, or None if cancelled
        """
        if field is None:
            print("⚠ Field selection cancelled")
            return

        print(f"✓ Selected field: {field.name}. Saving captured text...")
        self._process_capture(self.captured_text, field)

    def _process_capture(self, text: str, field: FieldInfo) -> None:
        """Process the captured text and selected field."""
        # Process the capture (save + index)
        self.processor.process_capture(field.path, text)

        # Create and invoke event
        event = HotkeyEvent(
            selected_text=text,
            selected_field=field,
        )

        if self.event_callback:
            self.event_callback(event)


def create_manager(config: Optional[HotkeyConfig] = None) -> HotkeyManager:
    """Create and return a hotkey manager instance."""
    return HotkeyManager(config)
