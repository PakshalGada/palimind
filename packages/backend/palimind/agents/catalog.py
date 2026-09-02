from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GLOBAL_AGENTS_DIR = Path.home() / ".palimind" / "agents"

TIER_POLICIES = ("tier1", "tier1+2", "all")
MEMORY_SCOPES = ("none", "session", "field")
VISIBILITIES = ("field", "global")
RUN_MODES = ("on_demand", "scheduled", "watcher")

_NAME_RE = re.compile(r"^[\w-]{1,64}$")

DEFAULT_MAX_ITERATIONS = 15


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class AgentDefinition:
    id: str
    name: str
    created_at: str
    system_prompt: str
    model: str
    temperature: float
    context_budget: int
    tools: list[str]
    tier_policy: str
    memory_scope: str
    memory_file: str
    visibility: str
    run_mode: str
    schedule: str | None
    watcher_pattern: str | None
    max_iterations: int
    human_in_loop_threshold: float
    write_access: bool
    shell_access: bool
    enabled: bool
    context_fields: list[str] = field(default_factory=list)
    color_seed: str = ""

    @property
    def avatar_seed(self) -> str:
        return self.color_seed or f"{self.id}{self.name}"

    # ── construction helpers ────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        name: str,
        *,
        system_prompt: str = "",
        model: str = "",
        temperature: float = 0.2,
        context_budget: int = 8000,
        tools: list[str] | None = None,
        tier_policy: str = "tier1+2",
        memory_scope: str = "field",
        visibility: str = "field",
        run_mode: str = "on_demand",
        schedule: str | None = None,
        watcher_pattern: str | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        human_in_loop_threshold: float = 0.0,
        write_access: bool = False,
        shell_access: bool = False,
        enabled: bool = True,
        context_fields: list[str] | None = None,
        field_root: Path | None = None,
        color_seed: str = "",
    ) -> AgentDefinition:
        created_at = _now_iso()
        defn = cls(
            id=str(uuid.uuid4()),
            name=name,
            created_at=created_at,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            context_budget=context_budget,
            tools=list(tools or []),
            tier_policy=tier_policy,
            memory_scope=memory_scope,
            memory_file="",
            visibility=visibility,
            run_mode=run_mode,
            schedule=schedule,
            watcher_pattern=watcher_pattern,
            max_iterations=max_iterations,
            human_in_loop_threshold=human_in_loop_threshold,
            write_access=write_access,
            shell_access=shell_access,
            enabled=enabled,
            context_fields=list(context_fields or []),
            color_seed=color_seed,
        )
        defn.set_memory_file(field_root)
        return defn

    # ── serialization ───────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentDefinition:
        known = {f.name for f in fields(cls)}
        cleaned = {k: v for k, v in data.items() if k in known}
        cleaned.setdefault("id", str(uuid.uuid4()))
        cleaned.setdefault("created_at", _now_iso())
        cleaned.setdefault("system_prompt", "")
        cleaned.setdefault("model", "")
        cleaned.setdefault("temperature", 0.2)
        cleaned.setdefault("context_budget", 8000)
        cleaned.setdefault("tools", [])
        cleaned.setdefault("tier_policy", "tier1+2")
        cleaned.setdefault("memory_scope", "field")
        cleaned.setdefault("memory_file", "")
        cleaned.setdefault("visibility", "field")
        cleaned.setdefault("run_mode", "on_demand")
        cleaned.setdefault("schedule", None)
        cleaned.setdefault("watcher_pattern", None)
        cleaned.setdefault("max_iterations", DEFAULT_MAX_ITERATIONS)
        cleaned.setdefault("human_in_loop_threshold", 0.0)
        cleaned.setdefault("write_access", False)
        cleaned.setdefault("shell_access", False)
        cleaned.setdefault("enabled", True)
        cleaned.setdefault("context_fields", [])
        cleaned.setdefault("color_seed", "")
        return cls(**cleaned)

    # ── memory file ─────────────────────────────────────────────────────

    def set_memory_file(self, field_root: Path | None = None) -> str:
        """Compute and persist the memory file path (global for all agents)."""
        if self.memory_scope == "none":
            self.memory_file = ""
        else:
            self.memory_file = str(GLOBAL_AGENTS_DIR / "memory" / f"{self.id}.json")
        return self.memory_file


def validate_definition(defn: AgentDefinition) -> str | None:
    """Return an error string for an invalid definition, else None."""
    if not _NAME_RE.match(defn.name):
        return "name must be 1-64 chars of letters, digits, underscore or dash (no spaces)"
    if defn.tier_policy not in TIER_POLICIES:
        return f"tier_policy must be one of {TIER_POLICIES}"
    if defn.memory_scope not in MEMORY_SCOPES:
        return f"memory_scope must be one of {MEMORY_SCOPES}"
    if defn.visibility not in VISIBILITIES:
        return f"visibility must be one of {VISIBILITIES}"
    if defn.run_mode not in RUN_MODES:
        return f"run_mode must be one of {RUN_MODES}"
    if defn.run_mode == "scheduled" and not defn.schedule:
        return "run_mode 'scheduled' requires a cron schedule"
    if defn.run_mode == "watcher" and not defn.watcher_pattern:
        return "run_mode 'watcher' requires a watcher_pattern glob"
    if not (0.0 <= defn.human_in_loop_threshold <= 1.0):
        return "human_in_loop_threshold must be in [0.0, 1.0]"
    return None


def validate_cron(expr: str) -> str | None:
    """Lightweight validation of a 5-field cron expression."""
    fields = expr.split()
    if len(fields) != 5:
        return "schedule must be a 5-field cron expression (minute hour dom month dow)"
    for idx, part in enumerate(fields):
        ranges = {
            0: (0, 59),
            1: (0, 23),
            2: (1, 31),
            3: (1, 12),
            4: (0, 7),
        }
        lo, hi = ranges[idx]
        for atom in part.split(","):
            atom = atom.strip()
            if atom == "*":
                continue
            if atom.startswith("*/") and atom[2:].isdigit():
                continue
            if "/" in atom:
                base, step = atom.split("/", 1)
                if not step.isdigit():
                    return f"invalid schedule field '{part}'"
                if base != "*" and not base.isdigit():
                    return f"invalid schedule field '{part}'"
                continue
            if "-" in atom:
                a, b = atom.split("-", 1)
                if not a.isdigit() or not b.isdigit():
                    return f"invalid schedule field '{part}'"
                a_i, b_i = int(a), int(b)
                if a_i < lo or b_i > hi:
                    return f"value out of range in schedule field '{part}'"
                continue
            if not atom.isdigit():
                return f"invalid schedule field '{part}'"
            val = int(atom)
            if val < lo or val > hi:
                return f"value out of range in schedule field '{part}'"
    return None


class AgentCatalog:
    """Owns all on-disk access to agent definitions.

    Definitions live in two locations:
      - global:   ~/.palimind/agents/{name}.json
      - field:    {field_root}/.palimind/agents/{name}.json

    Both are loaded and merged on load(); on a name collision the
    field-scoped definition wins.
    """

    def __init__(self, field_root: Path | None = None) -> None:
        self.field_root: Path | None = field_root
        self._by_id: dict[str, AgentDefinition] = {}
        self._by_name: dict[str, AgentDefinition] = {}
        self._lock = threading.Lock()

    # ── paths ───────────────────────────────────────────────────────────

    def _dir_for(self, defn: AgentDefinition) -> Path:
        # Agents are global — definitions always live in ~/.palimind/agents.
        return GLOBAL_AGENTS_DIR

    # ── loading / merging ───────────────────────────────────────────────

    def load(self) -> AgentCatalog:

        def _load_dir(path: Path, target: dict[str, tuple[AgentDefinition, int]]):
            if not path.exists():
                return
            for f in sorted(path.glob("*.json")):
                try:
                    data = json.loads(f.read_text("utf-8"))
                    defn = AgentDefinition.from_dict(data)
                    target[defn.name] = (defn, 0)
                except Exception as e:
                    print(f"[agents] skipping invalid definition {f}: {e}")

        target: dict[str, tuple[AgentDefinition, int]] = {}
        _load_dir(GLOBAL_AGENTS_DIR, target)

        with self._lock:
            self._by_name = {name: defn for name, (defn, _p) in target.items()}
            self._by_id = {defn.id: defn for defn in self._by_name.values()}
        return self

    # ── queries ─────────────────────────────────────────────────────────

    def all(self) -> list[AgentDefinition]:
        with self._lock:
            return sorted(self._by_name.values(), key=lambda d: d.name.lower())

    def enabled_agents(self) -> list[AgentDefinition]:
        return [d for d in self.all() if d.enabled]

    def get(self, name: str) -> AgentDefinition | None:
        with self._lock:
            return self._by_name.get(name)

    def get_by_id(self, agent_id: str) -> AgentDefinition | None:
        with self._lock:
            return self._by_id.get(agent_id)

    # ── mutation ────────────────────────────────────────────────────────

    def create(self, defn: AgentDefinition) -> AgentDefinition:
        error = validate_definition(defn)
        if error:
            raise ValueError(error)
        with self._lock:
            if defn.name in self._by_name:
                raise ValueError(f"An agent named '{defn.name}' already exists")
            defn.set_memory_file(self.field_root)
            self._write(defn)
            self._by_name[defn.name] = defn
            self._by_id[defn.id] = defn
        return defn

    def update(self, agent_id: str, changes: dict[str, Any]) -> AgentDefinition:
        with self._lock:
            existing = self._by_id.get(agent_id)
            if existing is None:
                raise KeyError(f"Agent not found: {agent_id}")
            data = existing.to_dict()
            data.update(changes)
            # id / created_at are immutable
            data["id"] = existing.id
            data["created_at"] = existing.created_at
            new_defn = AgentDefinition.from_dict(data)
            error = validate_definition(new_defn)
            if error:
                raise ValueError(error)
            if new_defn.name != existing.name and new_defn.name in self._by_name:
                raise ValueError(f"An agent named '{new_defn.name}' already exists")
            new_defn.set_memory_file(self.field_root)
            # remove old file if name changed
            old_path = self._dir_for(existing) / f"{existing.name}.json"
            new_path = self._dir_for(new_defn) / f"{new_defn.name}.json"
            self._write(new_defn)
            if old_path != new_path and old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass
            self._by_name.pop(existing.name, None)
            self._by_name[new_defn.name] = new_defn
            self._by_id[agent_id] = new_defn
            return new_defn

    def delete(self, agent_id: str) -> None:
        with self._lock:
            existing = self._by_id.get(agent_id)
            if existing is None:
                raise KeyError(f"Agent not found: {agent_id}")
            path = self._dir_for(existing) / f"{existing.name}.json"
            if path.exists():
                try:
                    path.unlink()
                except OSError as e:
                    raise OSError(f"Failed to delete agent file {path}: {e}") from e
            self._by_name.pop(existing.name, None)
            self._by_id.pop(agent_id, None)

    def _write(self, defn: AgentDefinition) -> None:
        path = self._dir_for(defn) / f"{defn.name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(defn.to_dict(), indent=2), "utf-8")


def migrate_field_agents(field_roots: list[Path]) -> int:
    """Copy any field-scoped agent definitions into the global agents dir.

    Agents are now global; field-scoped definitions are migrated once so the
    user keeps their agents. A same-named global agent is never overwritten
    (the field copy is skipped). Returns the number of migrated agents.
    """
    GLOBAL_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    migrated = 0
    seen_global = {p.stem for p in GLOBAL_AGENTS_DIR.glob("*.json")}
    for root in field_roots:
        if root is None:
            continue
        field_dir = Path(root) / ".palimind" / "agents"
        if not field_dir.is_dir():
            continue
        for f in sorted(field_dir.glob("*.json")):
            name = f.stem
            if name in seen_global:
                continue
            try:
                data = json.loads(f.read_text("utf-8"))
                defn = AgentDefinition.from_dict(data)
                if defn.name != name:
                    name = defn.name
                if name in seen_global:
                    continue
                defn.visibility = "global"
                defn.set_memory_file()
                target = GLOBAL_AGENTS_DIR / f"{defn.name}.json"
                if target.exists():
                    continue
                target.write_text(json.dumps(defn.to_dict(), indent=2), "utf-8")
                seen_global.add(defn.name)
                migrated += 1
            except Exception as e:
                print(f"[agents] failed to migrate field agent {f}: {e}")
    return migrated
