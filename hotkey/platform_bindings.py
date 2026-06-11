"""Cross-platform bindings for hotkey registration and clipboard access."""
from __future__ import annotations

import sys
import threading
import time
from typing import Callable, Optional

import pyperclip

try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False


class PlatformBindings:
    """Cross-platform hotkey and clipboard bindings."""

    def __init__(self):
        """Initialize platform bindings."""
        if not HAS_PYNPUT:
            raise ImportError(
                "pynput not installed. Install with: pip install -e '.[hotkey]'"
            )
        self.listener = None
        self.hotkey_callback: Optional[Callable[[], None]] = None
        self._last_clipboard = ""

    def register_hotkey(self, hotkey_combo: str, callback: Callable[[], None]) -> None:
        """
        Register a global hotkey listener.
        
        Args:
            hotkey_combo: Hotkey combination (e.g., "<ctrl>+<shift>+e" or "ctrl+shift+e")
            callback: Function to call when hotkey is pressed
        """
        self.hotkey_callback = callback
        
        # Convert standard modifiers to pynput format if they lack brackets
        parts = hotkey_combo.lower().split('+')
        formatted_parts = []
        for part in parts:
            if not part.startswith('<') and len(part) > 1 and part in ['ctrl', 'shift', 'alt', 'cmd', 'space', 'enter', 'esc', 'tab', 'backspace', 'delete', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12']:
                formatted_parts.append(f'<{part}>')
            else:
                formatted_parts.append(part)
        pynput_combo = '+'.join(formatted_parts)
        
        try:
            self.listener = keyboard.GlobalHotKeys({
                pynput_combo: self.hotkey_callback
            })
            self.listener.start()
            print(f"✓ Hotkey registered: {pynput_combo} (original: {hotkey_combo})")
        except Exception as e:
            raise ValueError(f"Invalid hotkey combination: {hotkey_combo} (parsed as {pynput_combo})") from e

    def stop_hotkey(self) -> None:
        """Stop listening for hotkey."""
        if self.listener:
            self.listener.stop()
            self.listener = None
            print("✓ Hotkey listener stopped")

    def get_clipboard_text(self) -> str:
        """
        Get text from system clipboard.
        
        Returns:
            Text from clipboard, or empty string if unavailable
        """
        try:
            return pyperclip.paste()
        except Exception as e:
            # Fallback to tkinter
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                text = root.clipboard_get()
                root.destroy()
                return text
            except Exception as tk_err:
                print(f"Clipboard read failed: pyperclip({e}), tkinter({tk_err})")
                return ""

    def set_clipboard_text(self, text: str) -> None:
        """
        Set text in system clipboard.
        
        Args:
            text: Text to copy to clipboard
        """
        try:
            pyperclip.copy(text)
        except Exception as e:
            # Fallback to tkinter
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                root.clipboard_clear()
                root.clipboard_append(text)
                root.update()
                root.destroy()
            except Exception as tk_err:
                print(f"Clipboard write failed: pyperclip({e}), tkinter({tk_err})")

    def simulate_copy(self) -> bool:
        """
        Simulate pressing Ctrl+C (Windows/Linux) or Cmd+C (macOS) to copy selected text.
        
        Returns:
            True if simulation succeeded, False otherwise
        """
        try:
            from pynput.keyboard import Controller, Key
            keyboard_controller = Controller()

            # Wait a brief moment for user to release hotkey keys
            time.sleep(0.25)

            # Programmatically release modifiers to prevent interference
            modifiers = [
                Key.ctrl, Key.ctrl_l, Key.ctrl_r,
                Key.alt, Key.alt_l, Key.alt_r,
                Key.shift, Key.shift_l, Key.shift_r,
                Key.cmd, Key.cmd_l, Key.cmd_r
            ]
            for mod in modifiers:
                try:
                    keyboard_controller.release(mod)
                except Exception:
                    pass

            is_mac = sys.platform == "darwin"

            if is_mac:
                # Command + C
                keyboard_controller.press(Key.cmd)
                keyboard_controller.press('c')
                time.sleep(0.05)
                keyboard_controller.release('c')
                keyboard_controller.release(Key.cmd)
            else:
                # Control + C
                keyboard_controller.press(Key.ctrl)
                keyboard_controller.press('c')
                time.sleep(0.05)
                keyboard_controller.release('c')
                keyboard_controller.release(Key.ctrl)

            # Allow some time for OS clipboard to update
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"Error simulating copy: {e}")
            return False

    def ensure_setup(self) -> None:
        """Verify platform bindings are properly set up."""
        try:
            # Test clipboard access
            test = self.get_clipboard_text()
            print(f"✓ Platform bindings ready (clipboard accessible)")
        except Exception as e:
            print(f"⚠ Warning: {e}")


# Singleton instance
_bindings = None


def get_platform_bindings() -> PlatformBindings:
    """Get or create platform bindings singleton."""
    global _bindings
    if _bindings is None:
        _bindings = PlatformBindings()
    return _bindings
