import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class FieldEventHandler(FileSystemEventHandler):
    def __init__(self, callback):
        self.callback = callback

    def on_any_event(self, event):
        if event.is_directory:
            return
        # Ignore changes to hidden/palimind directories
        parts = Path(event.src_path).parts
        if any(
            p.startswith(".") or p in ["node_modules", "__pycache__", "venv", ".venv"]
            for p in parts
        ):
            return
        self.callback(event.src_path)


class FieldWatcher:
    def __init__(self, root: Path, on_change_callback):
        self.root = Path(root).resolve()
        self.on_change_callback = on_change_callback
        self.observer = None
        self.debounce_timer = None
        self.lock = threading.Lock()

    def start(self):
        event_handler = FieldEventHandler(self._on_file_changed)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.root), recursive=True)
        self.observer.start()

    def stop(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join()
            except Exception:
                pass
            self.observer = None
        with self.lock:
            if self.debounce_timer:
                self.debounce_timer.cancel()
                self.debounce_timer = None

    def _on_file_changed(self, filepath):
        with self.lock:
            if self.debounce_timer:
                self.debounce_timer.cancel()
            self.debounce_timer = threading.Timer(2.0, self._trigger_callback)
            self.debounce_timer.start()

    def _trigger_callback(self):
        self.on_change_callback(self.root)
