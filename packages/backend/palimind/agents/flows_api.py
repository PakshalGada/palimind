"""HTTP surface for routine flows and the local calendar feed."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Request

from palimind.agents import flows, routines

router = APIRouter(prefix="/api", tags=["flows"])


@router.get("/flows")
async def list_flows(agent_id: str = ""):
    return {"flows": flows.list_flows(agent_id)}


@router.get("/flows/{flow_id}")
async def get_flow(flow_id: str):
    status = flows.flow_status(flow_id)
    return {"flow": status} if status else {"error": "Flow not found"}


@router.post("/flows/connect")
async def connect(req: Request):
    body = await req.json()
    try:
        flow = flows.connect(
            str(body.get("canvas_agent_id") or body.get("agent_id") or ""),
            str(body.get("routine_id") or ""),
            str(body.get("to_agent_id") or ""),
        )
        return {"flow": flow}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/flows/disconnect")
async def disconnect(req: Request):
    body = await req.json()
    try:
        flow = flows.disconnect(
            str(body.get("canvas_agent_id") or body.get("agent_id") or ""),
            str(body.get("routine_id") or ""),
            str(body.get("to_agent_id") or ""),
        )
        return {"flow": flow}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _calendar_token() -> str:
    from palimind.security.tokens import palimind_home

    path = palimind_home() / "calendar_token"
    if path.exists():
        value = path.read_text("utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, "utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return value


def _ics_escape(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


@router.get("/routines/calendar.ics")
async def calendar_feed(token: str = Query(default="")):
    from fastapi.responses import PlainTextResponse

    expected = _calendar_token()
    if not token or not secrets.compare_digest(token, expected):
        return PlainTextResponse("forbidden", status_code=403)
    now = datetime.now(UTC)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PaliMind//Routines//EN",
    ]
    try:
        from palimind.jobs.cron import next_cron_time

        for routine in routines.list_routines(limit=1000):
            if not routine.get("enabled") or routine.get("run_mode") != "scheduled":
                continue
            schedule = str(routine.get("schedule") or "")
            when = next_cron_time(schedule, now) if schedule else None
            if when is None:
                continue
            start = when.astimezone(UTC)
            end = start + timedelta(minutes=15)
            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{_ics_escape(str(routine.get('id')))}",
                    f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
                    f"SUMMARY:{_ics_escape(str(routine.get('name') or 'Routine'))}",
                    f"DESCRIPTION:{_ics_escape(str(routine.get('input') or ''))}",
                    "END:VEVENT",
                ]
            )
    except Exception:
        pass
    lines.append("END:VCALENDAR")
    return PlainTextResponse("\r\n".join(lines) + "\r\n", media_type="text/calendar")
