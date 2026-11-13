"""The workspace for one estate: the parsed models (from anaplan-estate),
plus the state the architect accumulates between runs. Nothing here is
sent anywhere by itself.

  <workspace>/
    statuses.json     pattern id -> {status, reason, by, when}
    memories.json     [{scope, text, when}]  scope: estate | model:<name> | rule:<id>
    transcripts/      one JSONL per chat session (question, tool calls, answer)
    reviews/          each review run (opinion json + markdown)
"""
from __future__ import annotations
import json, datetime, re
from dataclasses import dataclass, field
from pathlib import Path
from anaplan_estate import fleet
from anaplan_estate.fleet import EstateRun, ModelRun

STATUSES = ("open", "accepted", "deliberate", "wont_fix", "incorrect", "fixed")


def pattern_id(m: ModelRun, c) -> str:
    return f"{m.name}::{c.rule}::{c.label}"


@dataclass
class Workspace:
    root: Path
    estate: EstateRun
    statuses: dict = field(default_factory=dict)
    memories: list = field(default_factory=list)
    estate_id: str = ""        # set by the web layer (Orac estate id); the CLI uses the folder name
    snapshot_id: str = ""      # the snapshot the estate was read from; citation ids are bound to it
    backend: object = None     # an orac.bridge.Bridge: statuses and memories then live in the store, not in JSON
    edge_states: dict = field(default_factory=dict)   # {(from model, to model): {state, reason, by, when}}; absent = inferred from import names
    version: int = 0           # bumped whenever statuses, memories or edge states change: the material a session caches follows it

    def _changed(self, handles: bool = False) -> None:
        self.version += 1
        if handles:
            self.__dict__.pop("_handles", None)      # the decision handles the validator knows (plan keys, proposals) are recomputed

    # ---------- persistence ----------
    @classmethod
    def open(cls, exports_root: str | Path, workspace: str | Path | None = None, **run_kwargs) -> "Workspace":
        er = fleet.run(exports_root, **run_kwargs)
        ws = Path(workspace or Path(exports_root) / ".architect")
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "transcripts").mkdir(exist_ok=True); (ws / "reviews").mkdir(exist_ok=True)
        w = cls(ws, er)
        w.statuses = _read(ws / "statuses.json", {})
        w.memories = _read(ws / "memories.json", [])
        w.estate_id = Path(exports_root).name
        w.snapshot_id = "folder:" + Path(exports_root).name
        return w

    @classmethod
    def from_run(cls, er: EstateRun, workspace: str | Path, backend=None) -> "Workspace":
        """A workspace over an estate already parsed (Orac keeps the run per snapshot). With a backend,
        statuses and memories are read from the store and every change is written there."""
        ws = Path(workspace)
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "transcripts").mkdir(exist_ok=True); (ws / "reviews").mkdir(exist_ok=True)
        w = cls(ws, er)
        w.backend = backend
        if backend is not None:
            w.statuses = backend.statuses(); w.memories = backend.memories(); w.edge_states = backend.edge_states_by_name()
        else:
            w.statuses = _read(ws / "statuses.json", {})
            w.memories = _read(ws / "memories.json", [])
        return w

    def reload(self):
        if self.backend is not None:
            self.statuses = self.backend.statuses(); self.memories = self.backend.memories(); self.edge_states = self.backend.edge_states_by_name()
        self._changed(handles=True)

    def save(self):
        if self.backend is not None:
            return
        (self.root / "statuses.json").write_text(json.dumps(self.statuses, indent=1, ensure_ascii=False), encoding="utf-8")
        (self.root / "memories.json").write_text(json.dumps(self.memories, indent=1, ensure_ascii=False), encoding="utf-8")

    # ---------- statuses and memories ----------
    def set_status(self, pid: str, status: str, reason: str, by: str = "user") -> dict:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if self.backend is not None:
            rec = self.backend.set_status(pid, status, reason, by); self.statuses = self.backend.statuses(); self._changed(); return rec
        rec = {"status": status, "reason": reason, "by": by, "when": datetime.datetime.now().isoformat(timespec="seconds")}
        self.statuses[pid] = rec; self.save(); self._changed(); return rec

    def status_of(self, pid: str) -> str:
        return self.statuses.get(pid, {}).get("status", "open")

    # ---------- connections between models (the demo story, 2026-09-28) ----------
    def edge_state(self, from_name: str, to_name: str) -> dict | None:
        """The owner's word on a feed, or None when it rests on the import names alone."""
        return self.edge_states.get((from_name, to_name))

    def set_edge_state(self, from_name: str, to_name: str, state: str, reason: str, by: str = "user") -> dict | None:
        if self.backend is None:
            raise ValueError("connection states live in the store; run the web app")
        rec = self.backend.set_edge_state(from_name, to_name, state, reason, by)
        self.edge_states = self.backend.edge_states_by_name()
        self._changed()
        return rec

    def remember(self, scope: str, text: str, by: str = "user", title: str = "") -> dict:
        if self.backend is not None:
            rec = self.backend.remember(scope, text, by, title=title) if title else self.backend.remember(scope, text, by)
            self.memories = self.backend.memories(); self._changed(); return rec
        rec = {"scope": scope, "text": (title + ": " if title else "") + text.strip(), "by": by, "when": datetime.datetime.now().isoformat(timespec="seconds")}
        self.memories.append(rec); self.save(); self._changed(); return rec

    def memories_for(self, model: str | None = None, rules: set[str] | None = None) -> list[dict]:
        out = []
        for mm in self.memories:
            sc = mm["scope"]
            if sc == "estate" or (model and sc == f"model:{model}") or (rules and sc.startswith("rule:") and sc[5:] in rules):
                out.append(mm)
        return out

    # ---------- object index (for the validator and the tools) ----------
    def models(self) -> dict[str, ModelRun]:
        return {m.name: m for m in self.estate.models}

    def index(self) -> dict[str, set[str]]:
        """Every name a claim may cite, exactly as it appears in the material."""
        mods, lis, acts, rules, pats, names = set(), set(), set(), set(), set(), set()
        for m in self.estate.models:
            names.add(m.name)
            for mod in m.model.modules:
                mods.add(mod); mods.add(f"{m.name} :: {mod}")
            for (mod, li) in m.model.line_items:
                lis.add(f"{mod}.{li}"); lis.add(f"{m.name} :: {mod}.{li}")
            for a in m.actions.actions:
                acts.add(f"action:{a}")
            for p in m.actions.processes:
                acts.add(f"action:{p}")
            for r in m.lint.counts["by_rule"]:
                rules.add(f"finding:{r}")
            for c in m.clusters:
                pats.add(f"pattern:{pattern_id(m, c)}")
        return {"model": names, "module": mods, "line_item": lis, "action": acts, "finding": rules, "pattern": pats}

    def find_object(self, name: str, model: str | None = None):
        """Loose lookup: 'Module.Line Item', 'Line Item' (unique), or a module. Returns (kind, model_run, obj)."""
        name = name.strip().strip("'")
        cands = [self.models()[model]] if model and model in self.models() else self.estate.models
        for m in cands:
            if "." in name:
                for mod, li in m.model.line_items:
                    if f"{mod}.{li}".lower() == name.lower():
                        return "line_item", m, m.model.line_items[(mod, li)]
            if name in m.model.modules or name.lower() in {x.lower() for x in m.model.modules}:
                mod = next(x for x in m.model.modules if x.lower() == name.lower())
                return "module", m, m.model.modules[mod]
        for m in cands:
            hits = m.model.line_item_names().get(name) or [li for n, v in m.model.line_item_names().items() if n.lower() == name.lower() for li in v]
            if len(hits) == 1:
                return "line_item", m, hits[0]
            if len(hits) > 1:
                return "ambiguous", m, hits
        return None, None, None


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
