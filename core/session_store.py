from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any


def get_sessions_index_file(root: Path) -> Path:
    return root / ".palimind" / "sessions_index.json"


def get_sessions_dir(root: Path) -> Path:
    return root / ".palimind" / "sessions"


def get_session_file(root: Path, session_id: str) -> Path:
    return get_sessions_dir(root) / f"{session_id}.json"


def load_session_by_id(root: Path, session_id: str) -> dict | None:
    session_file = get_session_file(root, session_id)
    if not session_file.exists():
        return None
    try:
        return json.loads(session_file.read_text("utf-8"))
    except Exception:
        return None


def save_single_session(root: Path, session_data: dict):
    session_file = get_session_file(root, session_data["id"])
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(json.dumps(session_data, indent=2), "utf-8")


def load_sessions(root: Path) -> dict:
    index_file = get_sessions_index_file(root)
    sessions_dir = get_sessions_dir(root)
    old_file = root / ".palimind" / "sessions.json"

    if not index_file.exists() and old_file.exists():
        _migrate_from_old_format(root, old_file)
        return load_sessions(root)

    if not index_file.exists():
        return _create_default_sessions(root)

    try:
        index_data = json.loads(index_file.read_text("utf-8"))
        sessions_index = index_data.get("sessions", [])

        sessions = []
        for sess_meta in sessions_index:
            session_file = get_session_file(root, sess_meta["id"])
            if session_file.exists():
                full_sess = json.loads(session_file.read_text("utf-8"))
                sessions.append(full_sess)
            else:
                sess = dict(sess_meta)
                sess["messages"] = []
                sessions.append(sess)

        return {
            "active_session_id": index_data.get("active_session_id", ""),
            "sessions": sessions,
        }
    except Exception:
        return _create_default_sessions(root)


def _migrate_from_old_format(root: Path, old_file: Path):
    try:
        data = json.loads(old_file.read_text("utf-8"))
        active_id = data.get("active_session_id", "")
        sessions = data.get("sessions", [])

        sessions_index = []
        sessions_dir = get_sessions_dir(root)
        sessions_dir.mkdir(parents=True, exist_ok=True)

        for sess in sessions:
            sess_id = sess["id"]
            sessions_index.append({
                "id": sess_id,
                "name": sess.get("name", "Default Session"),
                "created_at": sess.get("created_at", time.time()),
            })
            session_file = get_session_file(root, sess_id)
            session_file.write_text(json.dumps(sess, indent=2), "utf-8")

        index_data = {
            "active_session_id": active_id,
            "sessions": sessions_index,
        }
        index_file = get_sessions_index_file(root)
        index_file.write_text(json.dumps(index_data, indent=2), "utf-8")

        backup = old_file.with_suffix(".json.bak")
        if backup.exists():
            backup.unlink()
        old_file.rename(backup)
    except Exception as e:
        print(f"Migration from old sessions.json failed: {e}")
        _create_default_sessions(root)


def _create_default_sessions(root: Path) -> dict:
    default_sess_id = str(uuid.uuid4())
    sess = {
        "id": default_sess_id,
        "name": "Default Session",
        "created_at": time.time(),
        "messages": [],
    }
    data = {
        "active_session_id": default_sess_id,
        "sessions": [sess],
    }
    _write_sessions_data(root, data)
    return data


def _write_sessions_data(root: Path, data: dict):
    sessions_dir = get_sessions_dir(root)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    sessions = data.get("sessions", [])
    sessions_index = []

    for sess in sessions:
        sess_id = sess["id"]
        sessions_index.append({
            "id": sess_id,
            "name": sess.get("name", "Default Session"),
            "created_at": sess.get("created_at", time.time()),
        })
        session_file = get_session_file(root, sess_id)
        session_file.write_text(json.dumps(sess, indent=2), "utf-8")

    index_data = {
        "active_session_id": data.get("active_session_id", ""),
        "sessions": sessions_index,
    }
    index_file = get_sessions_index_file(root)
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps(index_data, indent=2), "utf-8")

    # Remove orphaned session files (not in index)
    if sessions_dir.exists():
        indexed_ids = {s["id"] for s in sessions_index}
        for f in sessions_dir.iterdir():
            if f.suffix == ".json" and f.stem not in indexed_ids:
                try:
                    f.unlink()
                except Exception:
                    pass


def save_sessions(root: Path, data: dict):
    _write_sessions_data(root, data)


def add_new_session(root: Path, name: str) -> dict:
    data = load_sessions(root)
    sess_id = str(uuid.uuid4())
    new_sess = {
        "id": sess_id,
        "name": name,
        "created_at": time.time(),
        "messages": [],
    }
    data["sessions"].append(new_sess)
    data["active_session_id"] = sess_id
    save_sessions(root, data)
    return data


def set_active_session_id(root: Path, session_id: str) -> dict:
    data = load_sessions(root)
    exists = any(s["id"] == session_id for s in data["sessions"])
    if exists:
        data["active_session_id"] = session_id
        save_sessions(root, data)
    return data


def delete_session(root: Path, session_id: str) -> dict:
    data = load_sessions(root)
    sessions = data["sessions"]
    data["sessions"] = [s for s in sessions if s["id"] != session_id]

    session_file = get_session_file(root, session_id)
    if session_file.exists():
        session_file.unlink()

    if not data["sessions"]:
        default_sess_id = str(uuid.uuid4())
        new_sess = {
            "id": default_sess_id,
            "name": "Default Session",
            "created_at": time.time(),
            "messages": [],
        }
        data["sessions"] = [new_sess]
        data["active_session_id"] = default_sess_id
    elif data["active_session_id"] == session_id:
        data["active_session_id"] = data["sessions"][0]["id"]
    save_sessions(root, data)
    return data


def append_message_to_session(
    root: Path, session_id: str, role: str, content: str, sources: list[str] = None
):
    data = load_sessions(root)
    for sess in data["sessions"]:
        if sess["id"] == session_id:
            if not sess["messages"]:
                if role == "user":
                    sess["name"] = content
            msg = {
                "role": role,
                "content": content,
                "timestamp": time.time(),
            }
            if sources:
                msg["sources"] = sources
            sess["messages"].append(msg)
            break
    save_sessions(root, data)


async def background_update_memory(
    root: Path, session_id: str, new_user_msg: str, new_bot_msg: str
):
    await asyncio.sleep(2)
    from core.config import load_config
    from core.embedder import generate_embeddings_batch
    from core.generative.summariser import summarise_conversation
    from core.storage.chat_store import ChatVectorStore

    config = load_config(root)
    ollama_url = config.get("ollama_base_url")
    chat_model = config.get("chat_model")
    embed_model = config.get("embed_model")

    target_sess = load_session_by_id(root, session_id)
    if not target_sess:
        return

    recent_messages = target_sess.get("messages", [])[-6:]
    previous_summary = target_sess.get("summary", "")

    try:
        new_summary = await asyncio.to_thread(
            summarise_conversation,
            recent_messages,
            previous_summary,
            ollama_url,
            chat_model,
        )
        if new_summary:
            target_sess["summary"] = new_summary
            save_single_session(root, target_sess)
    except Exception as e:
        print(f"Failed to update summary: {e}")

    turn_content = f"User: {new_user_msg}\nAssistant: {new_bot_msg}"
    try:
        embs = await asyncio.to_thread(
            generate_embeddings_batch, [turn_content], ollama_url, embed_model
        )
        if embs and embs[0]:
            chunk_id = int(uuid.uuid4().int % (2**63))
            with ChatVectorStore(root) as vstore:
                vstore.insert(
                    [
                        {
                            "vector": embs[0],
                            "chunk_id": chunk_id,
                            "session_id": session_id,
                            "content": turn_content,
                        }
                    ]
                )
    except Exception as e:
        print(f"Failed to update episodic memory: {e}")
