"""Tests for core.opencode_auth (global OpenCode CLI auth.json storage).

Run from the repo root:
    python3 -m pytest tests/test_opencode_auth.py -v

Path isolation: every test redirects XDG_DATA_HOME (and HOME as a fallback)
into a per-test temp directory via monkeypatch.setenv, so the real
~/.local/share/opencode/auth.json is never touched.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

# Make the repo root importable regardless of how pytest was invoked.
ROOT_PATH = Path(__file__).resolve().parent.parent
if str(ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(ROOT_PATH))

from core.opencode_auth import (  # noqa: E402
    auth_path,
    get_key,
    masked_preview,
    remove_key,
    set_key,
)


@pytest.fixture(autouse=True)
def isolated_auth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point all global auth resolution at a throwaway directory."""
    data_home = tmp_path / "data-home"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    # Belt-and-braces: auth_path() prefers XDG_DATA_HOME, but redirect HOME
    # too so nothing can ever fall through to the developer's real profile.
    monkeypatch.setenv("HOME", str(tmp_path))
    return data_home


def _write_auth(payload: dict | str) -> None:
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, dict):
        text = json.dumps(payload, indent=2)
    else:
        text = payload
    path.write_text(text, encoding="utf-8")


class TestSetKey:
    def test_creates_file_and_parent_dirs_with_correct_format(self):
        assert not auth_path().exists()

        set_key("oc-secret-key-1234")

        path = auth_path()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {
            "opencode": {"type": "api", "key": "oc-secret-key-1234"}
        }

    def test_deeply_nested_parent_dirs_are_created(self, tmp_path: Path, monkeypatch):
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setenv("XDG_DATA_HOME", str(nested))

        set_key("another-secret-key")

        assert (nested / "opencode" / "auth.json").is_file()

    def test_preserves_sibling_provider_entries(self):
        siblings = {
            "openrouter": {"type": "api", "key": "sk-or-v1-existing"},
            "github-copilot": {"type": "oauth", "refresh": "r", "access": "a"},
        }
        _write_auth(siblings)

        set_key("brand-new-opencode-key")

        data = json.loads(auth_path().read_text(encoding="utf-8"))
        assert data["openrouter"] == siblings["openrouter"]
        assert data["github-copilot"] == siblings["github-copilot"]
        assert data["opencode"] == {"type": "api", "key": "brand-new-opencode-key"}

    def test_overwrites_own_previous_entry(self):
        set_key("first-key-value")
        set_key("second-key-value")

        data = json.loads(auth_path().read_text(encoding="utf-8"))
        assert data["opencode"]["key"] == "second-key-value"

    def test_raises_valueerror_on_corrupt_json_and_leaves_file_untouched(self):
        corrupt = "{not valid json!!"
        _write_auth(corrupt)

        with pytest.raises(ValueError, match="invalid JSON"):
            set_key("should-not-be-written")

        assert auth_path().read_text(encoding="utf-8") == corrupt

    def test_no_tmp_files_left_behind(self):
        set_key("cleanup-check-key")
        leftovers = [p.name for p in auth_path().parent.iterdir() if p != auth_path()]
        assert leftovers == []


class TestGetKey:
    def test_returns_none_when_file_missing(self):
        assert get_key() is None

    def test_roundtrip(self):
        set_key("round-trip-key-9999")
        assert get_key() == "round-trip-key-9999"

    def test_returns_none_for_missing_entry(self):
        _write_auth({"openrouter": {"type": "api", "key": "other-provider"}})
        assert get_key("opencode") is None

    def test_accepts_api_type_and_bare_key_entries(self):
        _write_auth(
            {
                "opencode": {"type": "api", "key": "typed-entry"},
                "legacy": {"key": "bare-key-entry"},
            }
        )
        assert get_key("opencode") == "typed-entry"
        assert get_key("legacy") == "bare-key-entry"

    def test_raises_valueerror_on_corrupt_json(self):
        _write_auth("{broken json")
        with pytest.raises(ValueError, match="invalid JSON"):
            get_key()


class TestNonObjectJson:
    """Top-level JSON that is not an object must fail loudly everywhere."""

    PAYLOAD = "[1, 2]"

    def test_get_raises_valueerror(self):
        _write_auth(self.PAYLOAD)
        with pytest.raises(ValueError, match="does not contain a JSON object"):
            get_key()

    def test_set_raises_valueerror_and_leaves_file_untouched(self):
        _write_auth(self.PAYLOAD)
        with pytest.raises(ValueError, match="does not contain a JSON object"):
            set_key("should-not-be-written")
        assert auth_path().read_text(encoding="utf-8") == self.PAYLOAD

    def test_remove_raises_valueerror_and_leaves_file_untouched(self):
        _write_auth(self.PAYLOAD)
        with pytest.raises(ValueError, match="does not contain a JSON object"):
            remove_key()
        assert auth_path().read_text(encoding="utf-8") == self.PAYLOAD


class TestRemoveKey:
    def test_returns_false_when_file_missing(self):
        assert remove_key() is False

    def test_removes_entry_and_preserves_others(self):
        _write_auth(
            {
                "opencode": {"type": "api", "key": "doomed-key"},
                "openrouter": {"type": "api", "key": "survivor"},
            }
        )

        assert remove_key() is True

        data = json.loads(auth_path().read_text(encoding="utf-8"))
        assert "opencode" not in data
        assert data["openrouter"] == {"type": "api", "key": "survivor"}
        assert get_key() is None

    def test_returns_false_when_entry_absent(self):
        _write_auth({"openrouter": {"type": "api", "key": "keep-me"}})
        assert remove_key() is False
        # File untouched.
        data = json.loads(auth_path().read_text(encoding="utf-8"))
        assert data["openrouter"]["key"] == "keep-me"

    def test_raises_valueerror_on_corrupt_json_and_leaves_file_byte_identical(self):
        corrupt = '{"opencode": {"type": "api", "key": "trunc'  # truncated JSON
        _write_auth(corrupt)

        with pytest.raises(ValueError, match="invalid JSON"):
            remove_key()

        assert auth_path().read_text(encoding="utf-8") == corrupt


class TestKeyValidation:
    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="non-empty"):
            set_key("")
        assert not auth_path().exists()

    def test_rejects_whitespace_only_string(self):
        with pytest.raises(ValueError, match="non-empty"):
            set_key("   \t\n  ")
        assert not auth_path().exists()


class TestUnreadableExistingFile:
    """M2 regression: an unreadable existing file must never be clobbered."""

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permissions",
    )
    def test_set_key_raises_instead_of_overwriting_unreadable_file(self):
        original = json.dumps(
            {"openrouter": {"type": "api", "key": "precious-sibling"}}, indent=2
        )
        _write_auth(json.loads(original))
        path = auth_path()
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                set_key("should-not-overwrite")
        finally:
            path.chmod(0o600)
        assert path.read_text(encoding="utf-8") == original

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        reason="root bypasses file permissions",
    )
    def test_get_key_raises_on_unreadable_file(self):
        _write_auth({"opencode": {"type": "api", "key": "hidden-key"}})
        path = auth_path()
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                get_key()
        finally:
            path.chmod(0o600)


class TestMaskedPreview:
    def test_last_four_chars_with_ellipsis(self):
        assert masked_preview("abcd1234wxyz") == "…wxyz"

    def test_short_keys_return_empty_string(self):
        assert masked_preview("") == ""
        assert masked_preview("ab") == ""
        assert masked_preview("abc") == ""

    def test_exactly_four_chars(self):
        assert masked_preview("abc4") == "…abc4"

    def test_never_reveals_more_than_four_chars(self):
        secret = "super-long-secret-key"
        preview = masked_preview(secret)
        assert len(preview) == 5  # ellipsis + 4 chars
        assert preview[0] == "…"
        assert preview[1:] == secret[-4:]


class TestPermissionsAndAtomicity:
    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_file_mode_is_0600(self):
        set_key("perm-check-key")
        mode = stat.S_IMODE(auth_path().stat().st_mode)
        assert mode == 0o600

    def test_xdg_data_home_override_is_respected(self, tmp_path: Path, monkeypatch):
        custom = tmp_path / "custom-xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom))
        assert auth_path() == custom / "opencode" / "auth.json"
