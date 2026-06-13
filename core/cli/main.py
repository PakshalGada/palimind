from core.cli.commands import app
import sys
from pathlib import Path

__all__ = ["app"]

if len(sys.argv) == 1 or any(arg in ["--help", "-h"] for arg in sys.argv):
    try:
        from core.cli.ui import print_startup_banner
        from core.config import load_config
        target_dir = Path(".").resolve()
        config = load_config(target_dir)
        print_startup_banner(config)
    except Exception:
        pass

if __name__ == "__main__":
    app()
