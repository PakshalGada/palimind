"""Deterministic model-failover policy.

The policy is intentionally pure: the runtime supplies the current model,
the configured backup list and the set of held models.  Tests can exercise
every failure class without a provider.
"""

from __future__ import annotations

import time
from typing import Any

CAUSES = (
    "billing",
    "provider_unavailable",
    "rate_limit",
    "authentication",
    "network",
    "timeout",
    "protocol",
    "unknown",
)
HOLD_SECONDS = 600.0


def classify_failure(error: Any) -> str:
    text = str(error or "").lower()
    if "billing" in text or "payment" in text or "quota" in text:
        return "billing"
    if "rate limit" in text or "429" in text:
        return "rate_limit"
    if "auth" in text or "401" in text or "403" in text or "api key" in text:
        return "authentication"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "network" in text or "connection" in text or "dns" in text:
        return "network"
    if "protocol" in text or "json" in text or "invalid response" in text:
        return "protocol"
    if "unavailable" in text or "503" in text or "502" in text or "500" in text:
        return "provider_unavailable"
    return "unknown"


class FailoverGate:
    def __init__(self, *, hold_seconds: float = HOLD_SECONDS) -> None:
        self.hold_seconds = float(hold_seconds)
        self._held: dict[str, float] = {}

    def hold(self, model_id: str, *, until: float | None = None) -> None:
        self._held[str(model_id)] = float(
            until if until is not None else time.time() + self.hold_seconds
        )

    def release(self, model_id: str) -> None:
        self._held.pop(str(model_id), None)

    def is_held(self, model_id: str, *, now: float | None = None) -> bool:
        expiry = self._held.get(str(model_id))
        if expiry is None:
            return False
        if (now or time.time()) >= expiry:
            self._held.pop(str(model_id), None)
            return False
        return True

    def choose(
        self,
        primary: dict[str, Any],
        backups: list[dict[str, Any]],
        *,
        installed: set[str] | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        primary_id = _model_id(primary)
        for backup in backups:
            model_id = _model_id(backup)
            if not model_id or model_id == primary_id:
                continue
            if installed is not None and model_id not in installed:
                continue
            if self.is_held(model_id, now=now):
                continue
            return backup
        return None


def _model_id(item: dict[str, Any]) -> str:
    model = str(item.get("model") or item.get("id") or "")
    provider = str(item.get("provider") or "")
    return f"{provider}/{model}" if provider and "/" not in model else model


def should_failover(*, cause: str, acted: bool, has_backup: bool) -> bool:
    """A turn fails over only when it did no work and a backup is ready."""
    return cause in CAUSES and not acted and has_backup
