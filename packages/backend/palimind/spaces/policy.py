"""Per-space domain policy and storage quota checks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from palimind.spaces.store import find_by_root


class PolicyError(ValueError):
    """A fetch/save was refused by the space's own policy."""


def _space(root: Path) -> dict | None:
    try:
        return find_by_root(Path(root))
    except Exception:  # noqa: BLE001
        return None


def domain_allowed(root: Path, url: str) -> tuple[bool, str]:
    space = _space(root)
    if not space:
        return True, ""
    mode = str(space.get("domain_mode") or "off").lower()
    if mode not in ("allow", "deny"):
        return True, ""
    domains = [str(item).lower().removeprefix(".") for item in space.get("domains") or []]
    if not domains:
        return True, ""
    try:
        host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    except Exception:
        return False, "That link has no usable hostname."
    matched = any(host == item or host.endswith("." + item) for item in domains)
    if mode == "allow" and not matched:
        return False, f"{host} is not on this space's allow list."
    if mode == "deny" and matched:
        return False, f"{host} is blocked by this space's deny list."
    return True, ""


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def space_usage(root: Path) -> dict:
    root = Path(root)
    sources_bytes = _dir_size(root / "sources")
    snapshot_bytes = _dir_size(root / ".palimind" / "raw")
    total = sources_bytes + snapshot_bytes
    space = _space(root) or {}
    quota = int(space.get("quota_bytes") or 0)
    return {
        "space_id": space.get("id"),
        "sources_bytes": sources_bytes,
        "snapshot_bytes": snapshot_bytes,
        "total_bytes": total,
        "quota_bytes": quota,
        "remaining_bytes": max(0, quota - total) if quota else None,
        "percent": round((total / quota) * 100, 1) if quota else None,
        "exceeded": bool(quota and total > quota),
    }


def check_quota(root: Path, incoming: int = 0) -> None:
    usage = space_usage(root)
    quota = int(usage.get("quota_bytes") or 0)
    if quota and int(usage["total_bytes"]) + max(0, int(incoming)) > quota:
        raise PolicyError(
            f"This space's storage quota is full "
            f"({usage['total_bytes']} / {quota} bytes). Raise the quota or remove sources."
        )
