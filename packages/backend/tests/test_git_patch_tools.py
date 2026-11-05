"""Tests for git read/write tools and unified-diff patching."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from palimind.llm.mixture_of_expert.tools import set_tool_context

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git is not installed")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "a.txt").write_text("old\n", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "initial")
    set_tool_context(tmp_path)
    try:
        yield tmp_path
    finally:
        set_tool_context(None)


def test_git_status_diff_log(repo: Path) -> None:
    from palimind.agents.tools.git.tool import git_diff, git_log, git_status

    assert "##" in git_status()
    (repo / "a.txt").write_text("new\n", encoding="utf-8")
    assert "-old" in git_diff()
    assert "+new" in git_diff()
    assert "initial" in git_log()


def test_git_commit(repo: Path) -> None:
    from palimind.agents.tools.git.tool import git_commit, git_log

    (repo / "a.txt").write_text("committed\n", encoding="utf-8")
    out = git_commit("update a", all=True)
    assert "Error" not in out
    assert "update a" in git_log()


def test_apply_patch(repo: Path) -> None:
    import importlib

    apply_patch = importlib.import_module("palimind.agents.tools.apply-patch.tool").apply_patch

    patch = """--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-old
+patched
"""
    out = apply_patch(patch)
    assert "Applied patch" in out
    assert (repo / "a.txt").read_text(encoding="utf-8") == "patched\n"


def test_apply_patch_rejects_traversal(repo: Path) -> None:
    import importlib

    apply_patch = importlib.import_module("palimind.agents.tools.apply-patch.tool").apply_patch

    out = apply_patch("--- a/../evil.txt\n+++ b/../evil.txt\n@@ -1 +1 @@\n-x\n+y\n")
    assert "unsafe path" in out
    assert not (repo.parent / "evil.txt").exists()
