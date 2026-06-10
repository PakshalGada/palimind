"""Tkinter-based field selector popup for hotkey capture."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Callable, Optional

from hotkey.models import FieldInfo


class FieldSelectorPopup:
    """Popup window for selecting which Field to save captured text to."""

    def __init__(self, fields: list[FieldInfo], on_select: Callable[[Optional[FieldInfo]], None]):
        """
        Initialize field selector popup.
        
        Args:
            fields: List of available fields
            on_select: Callback when field is selected (or cancelled)
        """
        self.fields = fields
        self.on_select = on_select
        self.selected_field: Optional[FieldInfo] = None
        self.window: Optional[tk.Tk] = None

    def show(self) -> None:
        """Show the popup window and wait for selection."""
        self.window = tk.Tk()
        self.window.title("Palimind - Select Field")
        self.window.geometry("400x300")
        self.window.attributes("-topmost", True)  # Always on top

        # Center on screen
        self.window.update_idletasks()
        x = (self.window.winfo_screenwidth() // 2) - (self.window.winfo_width() // 2)
        y = (self.window.winfo_screenheight() // 2) - (self.window.winfo_height() // 2)
        self.window.geometry(f"+{x}+{y}")

        # Title label
        title = tk.Label(
            self.window,
            text="Select a Field to save this capture:",
            font=("Arial", 12, "bold"),
            fg="#333",
        )
        title.pack(pady=15)

        # Field list frame
        frame = tk.Frame(self.window)
        frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # Radio button variable
        self.var = tk.StringVar(value=self.fields[0].path if self.fields else "")

        # Radio buttons for each field
        if self.fields:
            for field in self.fields:
                radio = tk.Radiobutton(
                    frame,
                    text=f"{field.name}",
                    variable=self.var,
                    value=field.path,
                    font=("Arial", 10),
                    fg="#333",
                )
                radio.pack(anchor=tk.W, pady=5)
        else:
            label = tk.Label(
                frame,
                text="No Fields available. Create one in Palimind.",
                font=("Arial", 10),
                fg="#999",
            )
            label.pack(pady=10)

        # Button frame
        btn_frame = tk.Frame(self.window)
        btn_frame.pack(pady=15)

        save_btn = tk.Button(
            btn_frame,
            text="Save",
            command=self._on_save,
            bg="#4CAF50",
            fg="white",
            font=("Arial", 10, "bold"),
            padx=20,
            pady=8,
        )
        save_btn.pack(side=tk.LEFT, padx=5)

        cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            command=self._on_cancel,
            bg="#999",
            fg="white",
            font=("Arial", 10),
            padx=20,
            pady=8,
        )
        cancel_btn.pack(side=tk.LEFT, padx=5)

        # Bind Enter key to save
        self.window.bind("<Return>", lambda e: self._on_save())
        self.window.bind("<Escape>", lambda e: self._on_cancel())

        # Focus on window
        self.window.focus_set()
        self.window.mainloop()

    def _on_save(self) -> None:
        """Handle save button click."""
        selected_path = self.var.get()
        if selected_path:
            self.selected_field = next(
                (f for f in self.fields if f.path == selected_path),
                None,
            )
        self.window.destroy()
        self.on_select(self.selected_field)

    def _on_cancel(self) -> None:
        """Handle cancel button click."""
        self.window.destroy()
        self.on_select(None)


class FieldInfoLoader:
    """Load available fields from global config."""

    @staticmethod
    def load_fields() -> list[FieldInfo]:
        """
        Load available fields from ~/.palimind_global.json.
        
        Returns:
            List of FieldInfo objects
        """
        global_config_path = Path.home() / ".palimind_global.json"
        fields = []

        if not global_config_path.exists():
            return fields

        try:
            with open(global_config_path) as f:
                data = json.load(f)

            for field_path in data.get("fields", []):
                path_obj = Path(field_path)
                if path_obj.exists() and path_obj.is_dir():
                    field_name = path_obj.name
                    is_active = field_path == data.get("active_field")
                    fields.append(
                        FieldInfo(
                            name=field_name,
                            path=field_path,
                            is_active=is_active,
                        )
                    )
        except Exception as e:
            print(f"Error loading fields: {e}")

        return fields


def show_field_selector(on_select: Callable[[Optional[FieldInfo]], None]) -> None:
    """
    Show field selector popup and invoke callback on selection.
    
    Args:
        on_select: Callback with selected FieldInfo or None if cancelled
    """
    fields = FieldInfoLoader.load_fields()
    popup = FieldSelectorPopup(fields, on_select)
    popup.show()
