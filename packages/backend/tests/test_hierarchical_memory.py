#!/usr/bin/env python3
"""Test script for Hierarchical Memory System (Short-term, Mid-term, Long-term)."""

import sys
import tempfile
import uuid
from pathlib import Path

# Add project root to sys.path
root_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_path))

from palimind.memory import format_hierarchical_memory_context
from palimind.session_store import save_sessions
from palimind.storage.chat_store import ChatVectorStore, search_chat_episodes


def test_hierarchical_memory_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        sess_id = str(uuid.uuid4())

        # 1. Populate session with 10 dummy messages
        data = {
            "active_session_id": sess_id,
            "sessions": [
                {
                    "id": sess_id,
                    "name": "Test Session",
                    "created_at": 1000.0,
                    "summary": "User is asking about Python asynchronous programming and fast API structures.",
                    "messages": [
                        {"role": "user", "content": f"Message {i}"}
                        if i % 2 == 0
                        else {"role": "assistant", "content": f"Response {i}"}
                        for i in range(10)
                    ],
                }
            ],
        }
        save_sessions(tmp_path, data)

        # 2. Insert dummy episodic memory vectors into ChatVectorStore
        dummy_vector = [0.1] * 768
        chunk_id_1 = 12345
        with ChatVectorStore(tmp_path) as vstore:
            vstore.insert(
                [
                    {
                        "vector": dummy_vector,
                        "chunk_id": chunk_id_1,
                        "session_id": sess_id,
                        "content": "User: What is asyncio?\nAssistant: Asyncio is a library to write concurrent code using the async/await syntax.",
                    }
                ]
            )

        # 3. Retrieve long-term memory directly
        episodes = search_chat_episodes(tmp_path, dummy_vector, limit=3)
        assert len(episodes) == 1, f"Expected 1 episode, got {len(episodes)}"
        assert "asyncio" in episodes[0]["content"], "Episode content mismatch"

        # 4. Test format_hierarchical_memory_context
        summary = "User is building a local RAG app."
        formatted = format_hierarchical_memory_context(summary, episodes)
        assert "Running Conversation Summary (Mid-term Memory)" in formatted
        assert "Relevant Past Conversations (Long-term Episodic Memory)" in formatted

        print("✔ Hierarchical Memory unit tests passed!")


if __name__ == "__main__":
    test_hierarchical_memory_structure()
