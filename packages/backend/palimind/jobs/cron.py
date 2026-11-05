"""Cron helpers shared by the scheduler and durable job service."""

from __future__ import annotations

from datetime import datetime, timedelta


def _field_matches(expr: str, value: int, lo: int, hi: int) -> bool:
    for atom in expr.split(","):
        atom = atom.strip()
        if atom == "*":
            return True
        if "/" in atom:
            base, step_text = atom.split("/", 1)
            try:
                step_value = int(step_text)
            except ValueError:
                continue
            if step_value <= 0:
                continue
            if base == "*":
                if (value - lo) % step_value == 0:
                    return True
            else:
                try:
                    start = int(base)
                except ValueError:
                    continue
                if value >= start and (value - start) % step_value == 0:
                    return True
            continue
        if "-" in atom:
            try:
                a, b = atom.split("-", 1)
                if lo <= int(a) <= int(b) <= hi and int(a) <= value <= int(b):
                    return True
            except ValueError:
                continue
            continue
        try:
            if int(atom) == value:
                return True
        except ValueError:
            continue
    return False


def _is_wildcard(expr: str) -> bool:
    return expr.strip().startswith("*")


def cron_matches(expr: str, dt: datetime | None = None) -> bool:
    """Return True if the 5-field cron expression matches *dt* (default now)."""
    if not expr:
        return False
    parts = expr.split()
    if len(parts) != 5:
        return False
    now = dt or datetime.now()
    dow = (now.weekday() + 1) % 7
    minute, hour, dom, month = now.minute, now.hour, now.day, now.month
    if not _field_matches(parts[0], minute, 0, 59):
        return False
    if not _field_matches(parts[1], hour, 0, 23):
        return False
    if not _field_matches(parts[3], month, 1, 12):
        return False
    dom_ok = _field_matches(parts[2], dom, 1, 31)
    dow_ok = _field_matches(parts[4], dow, 0, 7) or (dow == 0 and _field_matches(parts[4], 7, 0, 7))
    if _is_wildcard(parts[2]) or _is_wildcard(parts[4]):
        return dom_ok and dow_ok
    return dom_ok or dow_ok


def next_cron_time(expr: str, after: datetime | None = None) -> datetime | None:
    """Return the first minute strictly after *after* matching *expr*.

    Scans minute by minute for up to 366 days. Returns None for invalid or
    impossible expressions. This is intentionally simple and dependency-free;
    the scheduler ticks frequently, so a scan is only used when a recurring job
    completes.
    """
    if not expr or len(expr.split()) != 5:
        return None
    moment = (after or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = moment + timedelta(days=366)
    while moment <= limit:
        if cron_matches(expr, moment):
            return moment
        moment += timedelta(minutes=1)
    return None
