"""Local backup/restore with a versioned manifest and optional encryption.

Backups are gzip tar archives containing a ``manifest.json`` and a
``payload/home/...`` tree. The manifest records the format version, creation
time, each file's relative path, size and SHA-256. Restore validates the
manifest and every hash before writing anything.

Encryption is optional and passphrase-based, using scrypt key derivation plus
AES-GCM (an age-style authenticated envelope). Wrong passphrases, tampered
ciphertext, malformed archives and hash mismatches are all rejected.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import time
from pathlib import Path
from typing import Any

from palimind.security.tokens import palimind_home
from palimind.settings import BACKUP_DIR

BACKUP_FORMAT = "palimind-backup"
BACKUP_VERSION = 1
PASSPHRASE_MAGIC = b"PALIMIND-BACKUP-ENC-V1\n"
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


class BackupError(RuntimeError):
    """Raised for invalid, corrupted, tampered or unreadable backups."""


def backups_dir() -> Path:
    raw = str(BACKUP_DIR or "").strip()
    path = Path(raw).expanduser() if raw else palimind_home() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _walk_files(root: Path, *, skip: set[Path]) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if any(resolved == item or item in resolved.parents for item in skip):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def is_encrypted(data: bytes) -> bool:
    return data.startswith(PASSPHRASE_MAGIC)


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )


def encrypt_bytes(plain: bytes, passphrase: str) -> bytes:
    if not passphrase:
        return plain
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        salt = os.urandom(16)
        nonce = os.urandom(12)
        key = _derive_key(passphrase, salt)
        ciphertext = AESGCM(key).encrypt(nonce, plain, None)
        return PASSPHRASE_MAGIC + salt + nonce + ciphertext
    except Exception as exc:  # noqa: BLE001
        raise BackupError(f"Could not encrypt backup: {exc}") from exc


def decrypt_bytes(data: bytes, passphrase: str = "") -> bytes:
    if not is_encrypted(data):
        return data
    if not passphrase:
        raise BackupError("This backup is encrypted; a passphrase is required.")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        offset = len(PASSPHRASE_MAGIC)
        if len(data) < offset + 16 + 12 + 16:
            raise BackupError("Encrypted backup is truncated or corrupted.")
        salt = data[offset : offset + 16]
        nonce = data[offset + 16 : offset + 28]
        ciphertext = data[offset + 28 :]
        key = _derive_key(passphrase, salt)
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except BackupError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BackupError("Wrong passphrase or corrupted backup.") from exc


def _read_manifest(data: bytes) -> tuple[dict[str, Any], tarfile.TarFile]:
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except Exception as exc:  # noqa: BLE001
        raise BackupError(f"Not a valid PaliMind backup archive: {exc}") from exc
    try:
        member = tar.getmember("manifest.json")
        if not member.isfile():
            raise BackupError("Backup manifest is not a regular file.")
        raw = tar.extractfile(member)
        if raw is None:
            raise BackupError("Backup manifest could not be read.")
        manifest = json.loads(raw.read().decode("utf-8"))
    except KeyError as exc:
        tar.close()
        raise BackupError("Backup manifest is missing.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        tar.close()
        raise BackupError(f"Backup manifest is invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        tar.close()
        raise BackupError("Backup manifest is not an object.")
    if manifest.get("format") != BACKUP_FORMAT:
        tar.close()
        raise BackupError("Unknown backup format.")
    try:
        version = int(manifest.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version < 1 or version > BACKUP_VERSION:
        tar.close()
        raise BackupError(f"Unsupported backup version: {manifest.get('version')}")
    files = manifest.get("files")
    if not isinstance(files, list):
        tar.close()
        raise BackupError("Backup manifest has no file list.")
    return manifest, tar


def _safe_relative(path: str) -> Path:
    rel = Path(str(path).replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise BackupError(f"Unsafe path in backup manifest: {path}")
    return rel


def _validate_and_extract(
    tar: tarfile.TarFile,
    manifest: dict[str, Any],
    *,
    target_home: Path,
    overwrite: bool,
    restore_workspaces: bool = False,
) -> dict[str, int]:
    restored = 0
    skipped = 0
    target_home = target_home.resolve()
    workspace_sources = {
        str(item.get("label")): Path(str(item.get("source") or "")).expanduser().resolve()
        for item in (manifest.get("workspaces") or [])
        if isinstance(item, dict) and item.get("label") and item.get("source")
    }
    for entry in manifest.get("files") or []:
        if not isinstance(entry, dict):
            raise BackupError("Malformed file entry in backup manifest.")
        archive_path = str(entry.get("path") or "")
        target_root: Path | None
        if archive_path.startswith("payload/home/"):
            rel = _safe_relative(archive_path[len("payload/home/") :])
            target_root = target_home
        elif archive_path.startswith("payload/workspaces/"):
            if not restore_workspaces:
                skipped += 1
                continue
            rest = archive_path[len("payload/workspaces/") :]
            label, _, subpath = rest.partition("/")
            target_root = workspace_sources.get(label)
            if target_root is None:
                raise BackupError(f"Backup references an unknown workspace: {label}")
            rel = _safe_relative(subpath)
        else:
            raise BackupError(f"Unsupported backup path: {archive_path}")
        try:
            member = tar.getmember(archive_path)
        except KeyError as exc:
            raise BackupError(f"Backup is missing file: {archive_path}") from exc
        if not member.isfile():
            raise BackupError(f"Backup entry is not a regular file: {archive_path}")
        raw = tar.extractfile(member)
        if raw is None:
            raise BackupError(f"Could not read backup file: {archive_path}")
        data = raw.read()
        if _sha256(data) != str(entry.get("sha256") or ""):
            raise BackupError(f"Backup file failed integrity check: {archive_path}")
        target = (target_root / rel).resolve()
        if target != target_root and target_root not in target.parents:
            raise BackupError(f"Backup path escapes target: {archive_path}")
        if target.exists() and not overwrite:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        try:
            os.chmod(target, int(entry.get("mode") or 0o600))
        except OSError:
            pass
        restored += 1
    return {"restored": restored, "skipped": skipped}


def create_backup(
    archive_path: str | Path | None = None,
    *,
    home: str | Path | None = None,
    include_workspaces: list[str | Path] | None = None,
    passphrase: str = "",
    label: str = "",
) -> dict[str, Any]:
    """Create a local backup archive and return its metadata."""
    root = Path(home).expanduser().resolve() if home else palimind_home().resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if archive_path is None:
        archive = backups_dir() / f"palimind-backup-{stamp}.pmbackup"
    else:
        archive = Path(archive_path).expanduser()
        if archive.is_dir():
            archive = archive / f"palimind-backup-{stamp}.pmbackup"
    archive = archive.resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive == root or root in archive.parents:
        # The new archive must never be included in its own payload.
        skip_self = {archive}
    else:
        skip_self = set()
    workspace_roots: list[tuple[str, Path]] = []
    for index, workspace in enumerate(include_workspaces or []):
        path = Path(workspace).expanduser().resolve()
        if path.is_dir():
            workspace_roots.append((f"workspace-{index}", path))

    files: list[dict[str, Any]] = []
    manifest: dict[str, Any] = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": time.time(),
        "label": str(label or "")[:200],
        "home": str(root),
        "encrypted": bool(passphrase),
        "files": files,
        "workspaces": [{"label": label_, "source": str(path)} for label_, path in workspace_roots],
    }
    plain = io.BytesIO()
    with tarfile.open(fileobj=plain, mode="w:gz") as tar:
        for path in _walk_files(root, skip=skip_self | {backups_dir().resolve()}):
            data = path.read_bytes()
            rel = path.relative_to(root)
            arcname = f"payload/home/{rel.as_posix()}"
            info = tarfile.TarInfo(arcname)
            info.size = len(data)
            info.mode = path.stat().st_mode & 0o777
            info.mtime = int(path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
            files.append(
                {
                    "path": arcname,
                    "size": len(data),
                    "sha256": _sha256(data),
                    "mode": info.mode,
                }
            )
        # Workspaces are explicitly opt-in and only their .palimind folder is
        # backed up; source files are not duplicated into the archive.
        for label_, path in workspace_roots:
            state_dir = path / ".palimind"
            for file_path in _walk_files(state_dir, skip=skip_self):
                data = file_path.read_bytes()
                rel = file_path.relative_to(state_dir)
                arcname = f"payload/workspaces/{label_}/.palimind/{rel.as_posix()}"
                info = tarfile.TarInfo(arcname)
                info.size = len(data)
                info.mode = file_path.stat().st_mode & 0o777
                info.mtime = int(file_path.stat().st_mtime)
                tar.addfile(info, io.BytesIO(data))
                files.append(
                    {
                        "path": arcname,
                        "size": len(data),
                        "sha256": _sha256(data),
                        "mode": info.mode,
                    }
                )
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest_bytes)
        info.mode = 0o600
        tar.addfile(info, io.BytesIO(manifest_bytes))
    raw = plain.getvalue()
    payload = encrypt_bytes(raw, passphrase)
    archive.write_bytes(payload)
    return {
        "path": str(archive),
        "name": archive.name,
        "size": len(payload),
        "sha256": _sha256(payload),
        "encrypted": bool(passphrase),
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": manifest["created_at"],
        "label": manifest["label"],
        "files": len(files),
    }


def verify_backup(archive: str | Path, passphrase: str = "") -> dict[str, Any]:
    """Validate the envelope, manifest and every file hash without restoring."""
    path = Path(archive).expanduser()
    if not path.is_file():
        raise BackupError(f"Backup not found: {path}")
    data = decrypt_bytes(path.read_bytes(), passphrase)
    manifest, tar = _read_manifest(data)
    try:
        for entry in manifest.get("files") or []:
            if not isinstance(entry, dict):
                raise BackupError("Malformed file entry in backup manifest.")
            archive_path = str(entry.get("path") or "")
            member = tar.getmember(archive_path)
            raw = tar.extractfile(member)
            if raw is None or _sha256(raw.read()) != str(entry.get("sha256") or ""):
                raise BackupError(f"Backup file failed integrity check: {archive_path}")
    except KeyError as exc:
        raise BackupError(f"Backup is missing file: {exc}") from exc
    finally:
        tar.close()
    return {
        "valid": True,
        "encrypted": is_encrypted(path.read_bytes()),
        "version": manifest.get("version"),
        "created_at": manifest.get("created_at"),
        "label": manifest.get("label", ""),
        "files": len(manifest.get("files") or []),
    }


def restore_backup(
    archive: str | Path,
    *,
    passphrase: str = "",
    target_home: str | Path | None = None,
    overwrite: bool = True,
    restore_workspaces: bool = False,
) -> dict[str, Any]:
    """Restore a backup after validating its manifest and file hashes."""
    path = Path(archive).expanduser()
    if not path.is_file():
        raise BackupError(f"Backup not found: {path}")
    data = decrypt_bytes(path.read_bytes(), passphrase)
    manifest, tar = _read_manifest(data)
    target = Path(target_home).expanduser().resolve() if target_home else palimind_home().resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        result = _validate_and_extract(
            tar,
            manifest,
            target_home=target,
            overwrite=overwrite,
            restore_workspaces=restore_workspaces,
        )
    finally:
        tar.close()
    return {
        "status": "success",
        **result,
        "target_home": str(target),
        "version": manifest.get("version"),
        "encrypted": is_encrypted(path.read_bytes()),
        "files": len(manifest.get("files") or []),
    }


def list_backups(directory: str | Path | None = None) -> list[dict[str, Any]]:
    base = Path(directory).expanduser() if directory else backups_dir()
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.pmbackup"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            first = path.read_bytes()[: len(PASSPHRASE_MAGIC)]
            stat = path.stat()
            out.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "encrypted": first == PASSPHRASE_MAGIC,
                }
            )
        except OSError:
            continue
    return out


def default_backup_path() -> Path:
    return backups_dir()
