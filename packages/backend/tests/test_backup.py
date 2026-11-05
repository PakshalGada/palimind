"""Round-trip, tamper and corruption tests for local backups."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from palimind import backup


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PALIMIND_HOME", str(home))
    monkeypatch.delenv("PALIMIND_BACKUP_DIR", raising=False)
    yield home


def _seed(home: Path) -> None:
    (home / "agents").mkdir(exist_ok=True)
    (home / "uploads").mkdir(exist_ok=True)
    (home / "backups").mkdir(exist_ok=True)
    (home / "state.db").write_bytes(b"sqlite-state")
    (home / "agents" / "a.json").write_text('{"name":"a"}', encoding="utf-8")
    (home / "uploads" / "note.txt").write_text("hello", encoding="utf-8")
    (home / "backups" / "old.pmbackup").write_bytes(b"should-not-be-backed-up")


def test_plain_backup_restore_roundtrip(_home: Path) -> None:
    _seed(_home)
    meta = backup.create_backup(label="roundtrip")
    assert meta["files"] == 3  # state + agent + upload; backups/ excluded
    assert Path(meta["path"]).is_file()
    verified = backup.verify_backup(meta["path"])
    assert verified["valid"] is True
    assert verified["version"] == 1
    assert verified["files"] == 3

    (_home / "state.db").unlink()
    (_home / "agents" / "a.json").unlink()
    result = backup.restore_backup(meta["path"])
    assert result["status"] == "success"
    assert result["restored"] == 3
    assert (_home / "state.db").read_bytes() == b"sqlite-state"
    assert json.loads((_home / "agents" / "a.json").read_text("utf-8"))["name"] == "a"


def test_encrypted_backup_wrong_passphrase_and_tamper(_home: Path) -> None:
    _seed(_home)
    meta = backup.create_backup(passphrase="correct horse")
    assert meta["encrypted"] is True
    raw = Path(meta["path"]).read_bytes()
    assert backup.is_encrypted(raw) is True

    with pytest.raises(backup.BackupError, match="Wrong passphrase|corrupted"):
        backup.restore_backup(meta["path"], passphrase="wrong")

    tampered = bytearray(raw)
    tampered[-1] ^= 0xFF
    bad_path = _home / "tampered.pmbackup"
    bad_path.write_bytes(bytes(tampered))
    with pytest.raises(backup.BackupError):
        backup.restore_backup(bad_path, passphrase="correct horse")

    result = backup.restore_backup(meta["path"], passphrase="correct horse")
    assert result["restored"] == 3


def test_manifest_hash_mismatch_rejected(_home: Path) -> None:
    payload = b"payload-data"
    manifest = {
        "format": backup.BACKUP_FORMAT,
        "version": backup.BACKUP_VERSION,
        "created_at": 0,
        "files": [
            {
                "path": "payload/home/bad.txt",
                "size": len(payload),
                "sha256": "0" * 64,
                "mode": 0o600,
            }
        ],
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("payload/home/bad.txt")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        m = json.dumps(manifest).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(m)
        tar.addfile(info, io.BytesIO(m))
    path = _home / "bad.pmbackup"
    path.write_bytes(buf.getvalue())
    with pytest.raises(backup.BackupError, match="integrity"):
        backup.restore_backup(path)


def test_corrupt_archive_rejected(_home: Path) -> None:
    path = _home / "garbage.pmbackup"
    path.write_bytes(b"definitely not a backup")
    with pytest.raises(backup.BackupError):
        backup.restore_backup(path)


def test_backup_api_roundtrip(_home: Path) -> None:
    from fastapi.testclient import TestClient

    import palimind.api_server as server

    _seed(_home)
    client = TestClient(server.app)
    created = client.post("/api/backup", json={"label": "api"})
    assert created.status_code == 200
    meta = created.json()["backup"]
    assert meta["files"] == 3

    listed = client.get("/api/backup").json()["backups"]
    assert any(item["name"] == meta["name"] for item in listed)

    verified = client.post("/api/backup/verify", json={"path": meta["path"]}).json()
    assert verified["valid"] is True

    (_home / "state.db").unlink()
    no_confirm = client.post("/api/backup/restore", json={"path": meta["path"]})
    assert "confirm" in no_confirm.json()["error"]

    restored = client.post(
        "/api/backup/restore", json={"path": meta["path"], "confirm": True}
    ).json()
    assert restored["status"] == "success"
    assert (_home / "state.db").read_bytes() == b"sqlite-state"


def test_backup_cli_list_and_create(_home: Path) -> None:
    from typer.testing import CliRunner

    from palimind.cli.commands import app

    _seed(_home)
    runner = CliRunner()
    result = runner.invoke(app, ["backup", "create", "--label", "cli"])
    assert result.exit_code == 0, result.output
    listed = runner.invoke(app, ["backup", "list"])
    assert listed.exit_code == 0
    assert "palimind-backup" in listed.output
