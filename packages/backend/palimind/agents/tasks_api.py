"""HTTP surface for task lanes, mailbox deliveries, sections and side questions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from palimind.agents import approvals, mailbox, sections, tasks, threads
from palimind.agents.registry import get_registry

router = APIRouter(prefix="/api/agents", tags=["agent-tasks"])


def _agent(agent_id: str) -> Any:
    return get_registry().get_by_id(agent_id)


def _task_with_deliveries(task: dict[str, Any]) -> dict[str, Any]:
    return {
        **task,
        "deliveries": mailbox.list_deliveries(task_agent_id(task), task_id=task.get("id") or "", limit=50),
    }


def task_agent_id(task: dict[str, Any]) -> str:
    return str(task.get("agent_id") or "")


def _queue_task(agent_id: str, task: dict[str, Any], input_text: str) -> dict[str, Any] | None:
    from palimind.agents import queue

    delivery = mailbox.send(
        agent_id,
        input_text,
        sender_kind="user",
        sender_id="user",
        task_id=str(task.get("id") or ""),
        target_thread_id=str(task.get("thread_id") or ""),
        expects_reply=True,
    )
    try:
        item = queue.enqueue(
            "task",
            str(task["id"]),
            input_text,
            lane=f"task:{task['id']}",
            task_id=str(task["id"]),
            idempotency_key=f"task:{task['id']}",
            metadata={"delivery_id": delivery["id"]},
        )
    except Exception as exc:  # noqa: BLE001
        tasks.fail_task(str(task["id"]), str(exc))
        mailbox.fail(delivery["id"], str(exc))
        return {"delivery": delivery, "error": str(exc)}
    return {"delivery": delivery, "queue_item": item}


@router.get("/{agent_id}/tasks")
async def list_agent_tasks(agent_id: str, include_closed: bool = False, status: str = ""):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    return {
        "tasks": [
            _task_with_deliveries(task)
            for task in tasks.list_tasks(agent_id, status=status, include_closed=include_closed)
        ]
    }


@router.post("/{agent_id}/tasks")
async def create_agent_task(agent_id: str, req: Request):
    defn = _agent(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    body = await req.json()
    title = str(body.get("title") or body.get("task") or "Task").strip()
    input_text = str(body.get("input") or body.get("task") or title)
    parent_task_id = str(body.get("parent_task_id") or "")
    ok, reason = tasks.can_start_task(agent_id, defn)
    if not ok:
        return {"error": reason}
    try:
        task = tasks.create_task(
            agent_id,
            title,
            input_text=input_text,
            parent_task_id=parent_task_id,
            priority=int(body.get("priority") or 0),
        )
        queued = _queue_task(agent_id, task, input_text)
        return {"task": _task_with_deliveries(tasks.get_task(task["id"]) or task), "queued": queued}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Failed to create task: {exc}"}


@router.get("/{agent_id}/tasks/{task_id}")
async def get_agent_task(agent_id: str, task_id: str):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    return {"task": _task_with_deliveries(task)}


@router.patch("/{agent_id}/tasks/{task_id}")
async def update_agent_task(agent_id: str, task_id: str, req: Request):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    body = await req.json()
    allowed = {k: v for k, v in body.items() if k in {"title", "input", "result", "error", "metadata", "priority", "status"}}
    try:
        return {"task": _task_with_deliveries(tasks.update_task(task_id, **allowed) or task)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/{agent_id}/tasks/{task_id}")
async def delete_agent_task(agent_id: str, task_id: str):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    return {"deleted": tasks.delete_task(task_id)}


@router.post("/{agent_id}/tasks/{task_id}/send")
async def send_to_task(agent_id: str, task_id: str, req: Request):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    body = await req.json()
    text = str(body.get("text") or "")
    if not text:
        return {"error": "text is required"}
    delivery = mailbox.send(
        agent_id,
        text,
        sender_kind="user",
        sender_id="user",
        task_id=task_id,
        target_thread_id=str(task.get("thread_id") or ""),
        idempotency_key=str(body.get("client_message_id") or ""),
        expects_reply=True,
    )
    from palimind.agents import queue

    try:
        item = queue.enqueue(
            "task",
            task_id,
            text,
            lane=f"task:{task_id}",
            task_id=task_id,
            metadata={"delivery_id": delivery["id"]},
        )
        return {"delivery": delivery, "queue_item": item}
    except Exception as exc:  # noqa: BLE001
        return {"delivery": delivery, "error": str(exc)}


@router.post("/{agent_id}/tasks/{task_id}/stop")
async def stop_task(agent_id: str, task_id: str):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    return {"task": tasks.stop_task(task_id)}


@router.post("/{agent_id}/tasks/{task_id}/close")
async def close_task(agent_id: str, task_id: str):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    return {"task": tasks.close_task(task_id)}


@router.post("/{agent_id}/tasks/{task_id}/reopen")
async def reopen_task(agent_id: str, task_id: str):
    task = tasks.get_task(task_id)
    if task is None or str(task.get("agent_id")) != agent_id:
        return {"error": "Task not found"}
    try:
        return {"task": tasks.reopen_task(task_id)}
    except ValueError as exc:
        return {"error": str(exc)}


@router.post("/{agent_id}/messages")
async def send_agent_message(agent_id: str, req: Request):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    body = await req.json()
    text = str(body.get("text") or "")
    if not text:
        return {"error": "text is required"}
    task_id = str(body.get("task_id") or "")
    delivery = mailbox.send(
        agent_id,
        text,
        sender_kind=str(body.get("sender_kind") or "user"),
        sender_id=str(body.get("sender_id") or "user"),
        task_id=task_id,
        target_thread_id=str(body.get("thread_id") or ""),
        idempotency_key=str(body.get("client_message_id") or ""),
        expects_reply=bool(body.get("expects_reply", False)),
    )
    from palimind.agents import queue

    try:
        item = queue.enqueue(
            "task" if task_id else "agent",
            task_id or agent_id,
            text,
            lane=f"task:{task_id}" if task_id else "chat",
            task_id=task_id,
            metadata={"delivery_id": delivery["id"]},
        )
        return {"message_id": delivery["id"], "messageId": delivery["id"], "delivery": delivery, "queue_item": item}
    except Exception as exc:  # noqa: BLE001
        return {"message_id": delivery["id"], "messageId": delivery["id"], "delivery": delivery, "error": str(exc)}


@router.get("/{agent_id}/deliveries/{delivery_id}")
async def get_delivery(agent_id: str, delivery_id: str):
    delivery = mailbox.get_delivery(delivery_id)
    if delivery is None or str(delivery.get("target_agent_id")) != agent_id:
        return {"error": "Delivery not found"}
    return {"delivery": delivery, "events": mailbox.events(delivery_id)}


@router.post("/{agent_id}/interrupt")
async def interrupt_agent(agent_id: str, req: Request):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    from palimind.agents.runtime import cancel_agent

    body: dict[str, Any] = {}
    try:
        body = await req.json()
    except Exception:
        pass
    cancelled = cancel_agent(agent_id)
    for delivery in mailbox.list_deliveries(agent_id, status="queued", limit=100):
        if str(body.get("delivery_id") or "") and delivery["id"] != body["delivery_id"]:
            continue
        mailbox.cancel(delivery["id"])
    return {"cancelled_runs": cancelled, "reason": str(body.get("reason") or "")}


@router.post("/{agent_id}/context/clear")
async def clear_context(agent_id: str):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    thread = threads.ensure_chat_thread(agent_id)
    threads.reset_thread(str(thread["id"]), reason="api-context-clear")
    return {"ok": True, "thread_id": thread["id"]}


@router.get("/{agent_id}/pending")
async def pending(agent_id: str):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    items = [p for p in approvals.list_pending() if str(p.get("agent_id")) == agent_id]
    return {"prompts": [], "approvals": items, "browserTakeovers": []}


@router.get("/{agent_id}/waits")
async def list_agent_waits(agent_id: str, status: str = "open"):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    from palimind.agents import waits

    return {"waits": waits.list_waits(agent_id, status=status)}


@router.post("/{agent_id}/waits")
async def create_agent_wait(agent_id: str, req: Request):
    if _agent(agent_id) is None:
        return {"error": "Agent not found"}
    from palimind.agents import waits

    body = await req.json()
    try:
        return {"wait": waits.create_wait(agent_id, str(body.get("note") or ""), routine_id=str(body.get("routine_id") or ""))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/{agent_id}/waits/{wait_id}")
async def close_agent_wait(agent_id: str, wait_id: str, reason: str = ""):
    from palimind.agents import waits

    wait = waits.get_wait(wait_id)
    if wait is None or str(wait.get("agent_id")) != agent_id:
        return {"error": "Wait not found"}
    return {"wait": waits.close_wait(wait_id, reason=reason)}


@router.post("/{agent_id}/side-questions")
async def side_question(agent_id: str, req: Request):
    defn = _agent(agent_id)
    if defn is None:
        return {"error": "Agent not found"}
    body = await req.json()
    question = str(body.get("question") or "")
    earlier = body.get("earlier") if isinstance(body.get("earlier"), list) else []
    try:
        from palimind.agents.side_questions import ask

        answer = ask(defn, question, earlier=earlier)
        return {"answer": answer}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Side question failed: {exc}"}


@router.get("/sections/all")
async def list_sections():
    return {"sections": sections.list_sections()}


@router.post("/sections/create")
async def create_section(req: Request):
    body = await req.json()
    try:
        return {"section": sections.create_section(str(body.get("name") or ""), sort_order=int(body.get("sort_order") or 0))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.patch("/sections/{section_id}")
async def rename_section(section_id: str, req: Request):
    body = await req.json()
    try:
        return {"section": sections.rename_section(section_id, str(body.get("name") or ""))}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.delete("/sections/{section_id}")
async def delete_section(section_id: str):
    return {"deleted": sections.delete_section(section_id)}


@router.post("/sections/{section_id}/assign")
async def assign_section(section_id: str, req: Request):
    body = await req.json()
    agent_id = str(body.get("agent_id") or "")
    try:
        return {"agent": sections.assign_agent_section(agent_id, section_id).to_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


@router.post("/sections/unassign")
async def unassign_section(req: Request):
    body = await req.json()
    agent_id = str(body.get("agent_id") or "")
    try:
        return {"agent": sections.assign_agent_section(agent_id, "").to_dict()}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
