"""
Palimind Server Entry Point
----------------------------
This is the entry point used by PyInstaller to build the sidecar binary.
It is NOT used during normal `pm ui` development — only in the packaged desktop app.

Usage:
    palimind-server.exe --port 8732 [--log-file path/to/server.log]
"""
import argparse
import multiprocessing
import os
import sys


def main():
    # Required for PyInstaller + multiprocessing on Windows.
    # Must be called before any other code that spawns processes.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="Palimind AI Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--log-file", type=str, default=None, help="Path to log file")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    args = parser.parse_args()

    # Configure logging to file if requested (used by Tauri to capture stderr)
    if args.log_file:
        import logging
        log_dir = os.path.dirname(args.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        logging.basicConfig(
            filename=args.log_file,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    # When running as a PyInstaller bundle, __file__ paths break.
    # We patch sys.path so `core` and `hotkey` packages are found correctly.
    if getattr(sys, "frozen", False):
        # Running inside PyInstaller bundle
        bundle_dir = sys._MEIPASS  # type: ignore[attr-defined]
        sys.path.insert(0, bundle_dir)

    # Now import and run the FastAPI app
    from core.api_server import app
    import uvicorn

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        # Disable uvicorn's signal handlers — Tauri manages the process lifecycle
        access_log=True,
    )


if __name__ == "__main__":
    main()
