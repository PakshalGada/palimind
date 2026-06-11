"""Web-based field selector popup for hotkey capture."""
from __future__ import annotations

import json
import socket
import threading
import time
import webbrowser
from pathlib import Path
from typing import Callable, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from hotkey.models import FieldInfo


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


def _find_free_port() -> int:
    """Find an available ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def show_field_selector(captured_text: str, on_select: Callable[[Optional[FieldInfo]], None]) -> None:
    """
    Show web-based field selector popup and invoke callback on selection.
    
    Args:
        captured_text: The text that was captured on hotkey trigger
        on_select: Callback with selected FieldInfo or None if cancelled
    """
    app = FastAPI()
    port = _find_free_port()
    
    selection_event = threading.Event()
    selected_field_info: Optional[FieldInfo] = None
    
    ui_dir = Path(__file__).parent.parent / "ui"
    if ui_dir.exists():
        app.mount("/ui", StaticFiles(directory=ui_dir, html=True))

    @app.get("/api/fields")
    def get_fields():
        fields = FieldInfoLoader.load_fields()
        return {"fields": [{"name": f.name, "path": f.path, "is_active": f.is_active} for f in fields]}

    @app.get("/api/captured")
    def get_captured():
        return {"text": captured_text}

    @app.post("/api/select")
    async def select_field(req: Request):
        nonlocal selected_field_info
        data = await req.json()
        path = data.get("path")
        
        if path:
            fields = FieldInfoLoader.load_fields()
            selected_field_info = next((f for f in fields if f.path == path), None)
            
        selection_event.set()
        server.should_exit = True
        return {"status": "ok"}

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical")
    server = uvicorn.Server(config)
    
    def run_server():
        server.run()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait briefly for the server to start
    time.sleep(0.5)
    
    # Open the browser to the local server
    url = f"http://127.0.0.1:{port}/ui/template/hotkey.html"
    print(f"🔗 Opening field selector URL: {url}")
    webbrowser.open(url)
    
    # Block until selection is made or server shuts down
    selection_event.wait()
    
    # Invoke the callback
    on_select(selected_field_info)
