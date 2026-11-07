"""Phase 0/1 regression tests: providers, threads, tasks, mailbox, sections."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from palimind.agents import mailbox, queue, sections, tasks, threads
from palimind.agents.catalog import AgentDefinition
from palimind.agents.providers.base import ProviderEvent
from palimind.agents.providers.fake import FakeProvider
from palimind.agents.providers.registry import reset_provider_registry, get_provider_registry
from palimind.agents.registry import get_registry
from palimind.storage import state_store


@pytest.fixture()
def isolated(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PALIMIND_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("PALIMIND_HOME", str(tmp_path / "home"))
    import palimind.agents.catalog as catalog

    monkeypatch.setattr(catalog, "GLOBAL_AGENTS_DIR", tmp_path / "agents")
    state_store._initialised.clear()
    registry = get_registry()
    registry._by_id = {}
    registry._by_name = {}
    yield registry
    registry._by_id = {}
    registry._by_name = {}
    state_store._initialised.clear()


@pytest.fixture()
def an_agent(isolated):
    return isolated.create(AgentDefinition.new("task-alpha", display_name="Alpha"))


def test_provider_contract_with_fake() -> None:
    reset_provider_registry()
    fake = FakeProvider(events=[ProviderEvent("message", {"text": "hello"}), ProviderEvent("usage", {"prompt_tokens": 2, "completion_tokens": 3})])
    get_provider_registry().register("fake", lambda: fake)

    async def run():
        models = await get_provider_registry().models("fake")
        assert models[0].id == "fake-large"
        session = await fake.start_session("thread-1", model="fake-large")
        events = [event async for event in fake.send_turn(session, [{"role": "user", "content": "hi"}], model="fake-large")]
        assert [e.type for e in events][:2] == ["turn_started", "message"]
        assert events[-1].type == "turn_completed"
        await fake.close()

    asyncio.run(run())
    assert fake.closed is True


def test_threads_are_unique_and_bind_provider_session(an_agent) -> None:
    first = threads.ensure_chat_thread(an_agent.id)
    second = threads.ensure_chat_thread(an_agent.id)
    assert first["id"] == second["id"]
    assert first["kind"] == "chat"
    bound = threads.bind_provider_session(first["id"], "fake", "session-1", fingerprint="v1")
    assert bound["session_id"] == "session-1"
    assert threads.get_thread(first["id"])["provider_session_id"] == "session-1"
    threads.reset_thread(first["id"])
    assert threads.get_provider_session(first["id"]) is None
    assert threads.get_thread(first["id"])["metadata"]["context_resets"]


def test_task_limits_and_lifecycle(an_agent) -> None:
    first = tasks.create_task(an_agent.id, "Research", input_text="find papers")
    second = tasks.create_task(an_agent.id, "Draft", input_text="write")
    assert first["status"] == "open"
    assert tasks.open_task_count(an_agent.id) == 2
    assert tasks.can_start_task(an_agent.id, an_agent)[0] is True
    tasks.mark_running(first["id"])
    tasks.mark_running(second["id"])
    assert tasks.can_start_task(an_agent.id, an_agent)[0] is False  # default limit 2
    tasks.complete_task(first["id"], "done")
    tasks.complete_task(second["id"], "done")
    assert tasks.close_task(first["id"])["status"] == "closed"
    assert tasks.reopen_task(first["id"])["status"] == "open"
    assert tasks.delete_task(second["id"]) is True
    assert tasks.open_task_count(an_agent.id) == 1


def test_mailbox_idempotency_states_and_reactions(an_agent) -> None:
    first = mailbox.send(
        an_agent.id,
        "hello",
        sender_kind="user",
        sender_id="user",
        idempotency_key="same-key",
    )
    second = mailbox.send(
        an_agent.id,
        "different text",
        sender_kind="user",
        sender_id="user",
        idempotency_key="same-key",
    )
    assert first["id"] == second["id"]
    assert mailbox.pending_count(an_agent.id) == 1
    claimed = mailbox.claim(first["id"])
    assert claimed["status"] == "starting" and claimed["attempts"] == 1
    mailbox.mark_running(first["id"])
    done = mailbox.complete(first["id"], "answer")
    assert done["status"] == "completed" and done["answer"] == "answer"
    assert [e["type"] for e in mailbox.events(first["id"])][:3] == ["queued", "starting", "running"]
    reaction = mailbox.react("message-1", "👍", actor_id=an_agent.id)
    assert reaction["emoji"] == "👍"
    assert mailbox.list_reactions("message-1")


def test_task_queue_runs_the_lane(an_agent, monkeypatch) -> None:
    task = tasks.create_task(an_agent.id, "Do work", input_text="perform work")
    delivery = mailbox.send(
        an_agent.id, "perform work", task_id=task["id"], target_thread_id=task["thread_id"]
    )
    item = queue.enqueue(
        "task",
        task["id"],
        "perform work",
        lane=f"task:{task['id']}",
        task_id=task["id"],
        metadata={"delivery_id": delivery["id"]},
    )
    assert item["lane"] == f"task:{task['id']}"
    assert queue.next_due()["id"] == item["id"]

    async def fake_run(defn, text, session_id="", **kwargs):
        return "done: " + text

    monkeypatch.setattr("palimind.agents.service.run_agent", fake_run)
    monkeypatch.setattr("palimind.agents.scheduler.recorded_run_status", lambda *a, **k: "success")
    asyncio.run(queue._execute(item))
    assert tasks.get_task(task["id"])["status"] == "completed"
    assert mailbox.get_delivery(delivery["id"])["status"] == "completed"
    assert queue.get_item(item["id"])["status"] == "done"


def test_sections_assign_and_delete(an_agent) -> None:
    section = sections.create_section("Research")
    assert sections.list_sections()[0]["name"] == "Research"
    updated = sections.assign_agent_section(an_agent.id, section["id"])
    assert updated.section_id == section["id"]
    assert sections.rename_section(section["id"], "Lab")["name"] == "Lab"
    assert sections.delete_section(section["id"]) is True
    assert get_registry().get_by_id(an_agent.id).section_id == ""
