"""`pm ui` must reinstall npm deps / rebuild the UI after a pull, not only
when node_modules / dist are missing."""

import os
from pathlib import Path

from palimind.cli.commands import (
    _REQUIRED_SERVER_ROUTES,
    desktop_sidecar_missing,
    frontend_build_stale,
    missing_required_routes,
    npm_deps_stale,
)


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


def test_missing_required_routes_detects_a_stale_server() -> None:
    old = {"paths": {"/health": {}, "/api/chat": {}}}
    assert missing_required_routes(old) == list(_REQUIRED_SERVER_ROUTES)

    current = {"paths": {route: {} for route in _REQUIRED_SERVER_ROUTES}}
    assert missing_required_routes(current) == []
    assert missing_required_routes({}) == list(_REQUIRED_SERVER_ROUTES)


def test_desktop_sidecar_missing(tmp_path: Path) -> None:
    bin_dir = tmp_path / "apps" / "desktop" / "src-tauri" / "binaries"
    assert desktop_sidecar_missing(tmp_path)  # fresh clone: no binaries dir
    _touch(bin_dir / ".palimind-desktop-x86_64-unknown-linux-gnu.123", 100)
    assert desktop_sidecar_missing(tmp_path)  # a half-staged temp file doesn't count
    _touch(bin_dir / "palimind-desktop-x86_64-unknown-linux-gnu", 100)
    assert not desktop_sidecar_missing(tmp_path)
