"""Knowledge spaces (containers above the folder-based index)."""

from palimind.spaces.store import (
    SpaceError,
    active_space_id,
    create_space,
    default_parent,
    delete_space,
    ensure_active_space,
    find_by_root,
    get_space,
    list_spaces,
    migrate_legacy_fields,
    resolve_space,
    set_active_space,
    update_space,
)

__all__ = [
    "SpaceError",
    "active_space_id",
    "create_space",
    "default_parent",
    "delete_space",
    "ensure_active_space",
    "find_by_root",
    "get_space",
    "list_spaces",
    "migrate_legacy_fields",
    "resolve_space",
    "set_active_space",
    "update_space",
]
