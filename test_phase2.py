from __future__ import annotations

from core.teams.manager import get_manager


def main() -> None:
    manager = get_manager()

    session = manager.create_session("/home/pakshal/Work/apple_data")
    sid = session.session_id
    print(f"Created session: {sid} for field {session.field_path}")
    assert session.get_guest("anything") is None
    print(f"Empty before guests: {len(session.guests)} guests")

    g1 = session.add_guest("tok-1", "Alice")
    g2 = session.add_guest("tok-2", "Bob")
    print(f"Added guests: {g1.display_name} ({g1.permission}), {g2.display_name} ({g2.permission})")

    assert session.get_guest("tok-1") is g1
    assert session.get_guest("tok-2") is g2
    print(f"Both guests retrievable: {len(session.guests)} in session")

    # confirm manager lookup by id works too
    assert manager.get_session(sid) is session
    print("manager.get_session(sid) returns the same session")

    session.remove_guest("tok-1")
    assert session.get_guest("tok-1") is None
    assert session.get_guest("tok-2") is g2
    print("After remove_guest('tok-1'): tok-1 gone, tok-2 still present")

    # message history
    session.append_message("host", "Host", "Welcome to the shared Palispace")
    session.append_message("guest", "Bob", "Thanks!")
    assert len(session.message_history) == 2
    assert session.message_history[1]["sender_name"] == "Bob"
    print(f"Message history has {len(session.message_history)} entries")

    manager.end_session(sid)
    assert manager.get_session(sid) is None
    print("After end_session: get_session(sid) is None")

    # singleton identity
    assert get_manager() is manager
    print("get_manager() returns the same singleton")

    print("\nALL PHASE 2 CHECKS PASSED")


if __name__ == "__main__":
    main()