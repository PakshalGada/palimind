import hashlib
from pathlib import Path

import typer

from ..config import db_path
from ..retrieval.store import Store


def file_hash(path: Path) -> str:
    """MD5 hash of file contents — fast enough for change detection."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def require_index(root: Path) -> None:
    if not db_path(root).exists():
        typer.echo("No index found. Run `pm init` first.")
        raise typer.Exit(code=1)


def open_store(root: Path) -> Store:
    return Store(db_path(root))
