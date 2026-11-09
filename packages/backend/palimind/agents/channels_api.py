"""HTTP surface for shared channels."""

from __future__ import annotations

from fastapi import APIRouter, Request

from palimind.agents import channels

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
async def list_channels(include_archived: bool = True):
    return {"channels": channels.list_channels(include_archived=include_archived)}


@router.post("")
async def create_channel(req: Request):
    body = await req.json()
    try:
        channel = channels.create_channel(
            str(body.get("name") or ""),
            purpose=str(body.get("purpose") or ""),
            members=[str(m) for m in (body.get("members") or [])],
            lead_agent_id=str(body.get("lead_agent_id") or ""),
            metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
        )
        return {"channel": channels.channel_detail(channel["id"])}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/{channel_id}")
async def get_channel(channel_id: str):
    detail = channels.channel_detail(channel_id)
    return {"channel": detail} if detail else {"error": "Channel not found"}


@router.patch("/{channel_id}")
async def update_channel(channel_id: str, req: Request):
    body = await req.json()
    try:
        channel = channels.update_channel(channel_id, **body)
        return (
            {"channel": channels.channel_detail(channel["id"])}
            if channel
            else {"error": "Channel not found"}
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/{channel_id}")
async def delete_channel(channel_id: str):
    return {"deleted": channels.delete_channel(channel_id)}


@router.post("/{channel_id}/archive")
async def archive_channel(channel_id: str):
    channel = channels.archive_channel(channel_id)
    return {"channel": channel} if channel else {"error": "Channel not found"}


@router.post("/{channel_id}/restore")
async def restore_channel(channel_id: str):
    channel = channels.restore_channel(channel_id)
    return {"channel": channel} if channel else {"error": "Channel not found"}


@router.post("/{channel_id}/members")
async def add_member(channel_id: str, req: Request):
    body = await req.json()
    try:
        member = channels.add_member(
            channel_id,
            str(body.get("agent_id") or ""),
            role=str(body.get("role") or ""),
            instructions=str(body.get("instructions") or ""),
        )
        return {"member": member}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/{channel_id}/members/{agent_id}")
async def remove_member(channel_id: str, agent_id: str):
    return {"removed": channels.remove_member(channel_id, agent_id)}


@router.post("/{channel_id}/lead")
async def set_lead(channel_id: str, req: Request):
    body = await req.json()
    try:
        return {"channel": channels.set_lead(channel_id, str(body.get("agent_id") or ""))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/{channel_id}/messages")
async def list_messages(channel_id: str, limit: int = 100, before_seq: int | None = None):
    return {"messages": channels.list_messages(channel_id, limit=limit, before_seq=before_seq)}


@router.post("/{channel_id}/messages")
async def send_message(channel_id: str, req: Request):
    body = await req.json()
    try:
        result = channels.route_message(
            channel_id,
            str(body.get("text") or ""),
            author_kind=str(body.get("author_kind") or "user"),
            author_id=str(body.get("author_id") or "user"),
            explicit_agent_id=str(body.get("agent_id") or ""),
            reply_to_task_id=str(body.get("reply_to_task_id") or ""),
            operation_id=str(body.get("operation_id") or ""),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/{channel_id}/tasks")
async def list_tasks(channel_id: str, status: str = "", limit: int = 100):
    return {"tasks": channels.list_tasks(channel_id, status=status, limit=limit)}


@router.post("/{channel_id}/tasks/{task_id}/stop")
async def stop_task(channel_id: str, task_id: str):
    task = channels.get_task(task_id)
    if task is None or str(task.get("channel_id")) != channel_id:
        return {"error": "Task not found"}
    return {"task": channels.stop_task(task_id)}


@router.post("/{channel_id}/tasks/{task_id}/reassign")
async def reassign_task(channel_id: str, task_id: str, req: Request):
    body = await req.json()
    task = channels.get_task(task_id)
    if task is None or str(task.get("channel_id")) != channel_id:
        return {"error": "Task not found"}
    try:
        return {"task": channels.transfer_task(task_id, str(body.get("agent_id") or ""))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.get("/{channel_id}/memories")
async def list_memories(channel_id: str):
    return {"memories": channels.list_memories(channel_id)}


@router.post("/{channel_id}/memories")
async def set_memory(channel_id: str, req: Request):
    body = await req.json()
    try:
        return channels.set_memory(
            channel_id, str(body.get("key") or ""), str(body.get("value") or "")
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
