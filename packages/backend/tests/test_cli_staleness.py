"""`pm ui` must reinstall npm deps / rebuild the UI after a pull, not only
when node_modules / dist are missing."""

import os
from pathlib import Path

from palimind.cli.commands import frontend_build_stale, npm_deps_stale


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def test_npm_deps_stale_when_missing(tmp_path: Path) -> None:
    _touch(tmp_path / "package.json", 100)
    assert npm_deps_stale(tmp_path)


def test_npm_deps_stale_after_lockfile_changes(tmp_path: Path) -> None:
    _touch(tmp_path / "package.json", 100)
    _touch(tmp_path / "package-lock.json", 100)
    _touch(tmp_path / "node_modules" / ".package-lock.json", 200)
    assert not npm_deps_stale(tmp_path)
    # A pull that adds a dependency rewrites the lockfile.
    _touch(tmp_path / "package-lock.json", 300)
    assert npm_deps_stale(tmp_path)


def test_frontend_build_stale(tmp_path: Path) -> None:
    assert frontend_build_stale(tmp_path)  # no dist at all
    _touch(tmp_path / "src" / "design" / "theme.css", 100)
    _touch(tmp_path / "dist" / "index.html", 200)
    assert not frontend_build_stale(tmp_path)
    _touch(tmp_path / "src" / "design" / "theme.css", 300)
    assert frontend_build_stale(tmp_path)
