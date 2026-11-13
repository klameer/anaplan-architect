"""What the Workspace reads and writes when it is backed by the store instead of
statuses.json and memories.json: statuses come from finding_state, memories
from notes. The material builder, the tools and the review keep their shapes.
"""
from __future__ import annotations
from .db import Db
from . import notes as notesmod, findings_state as fstate


class Bridge:
    def __init__(self, db: Db, estate_id: str, snapshot_id: str | None = None, user: str | None = None):
        self.db, self.estate_id, self.snapshot_id, self.user = db, estate_id, snapshot_id, user

    def statuses(self) -> dict:
        return fstate.as_statuses(self.db, self.estate_id)

    def memories(self) -> list[dict]:
        return notesmod.as_memories(self.db, self.estate_id)

    def set_status(self, pid: str, status: str, reason: str, by: str = "user") -> dict:
        r = fstate.set_state(self.db, self.estate_id, pid, status, reason, by=self.user or (None if by in ("user", "chat") else by), snapshot_id=self.snapshot_id)
        return {"status": r["state"], "reason": r["reason"], "by": r["by"] or by, "when": r["updated"]}

    def remember(self, scope: str, text: str, by: str = "user", title: str = "") -> dict:
        """The chat tool's `remember`: a conclusion, working assumption, scoped as the tool said."""
        n = notesmod.create(self.db, self.estate_id, text, title=title, objects=[scope], type="conclusion", status="working_assumption",
                            author=self.user, origin_kind="chat_tool" if by == "chat" else "user")
        return {"scope": scope, "text": n["body"], "by": by, "when": n["created"], "id": n["id"]}

    # ---------- connections between models (the demo story, 2026-09-28) ----------
    def _model_names(self) -> dict:
        return {r["id"]: r["name"] for r in self.db.q("SELECT id, name FROM models WHERE estate_id=?", self.estate_id)}

    def edge_states_by_name(self) -> dict:
        """{(from model name, to model name): {state, reason, by, when, snapshot}}; a feed with no row is inferred."""
        names = self._model_names()
        out = {}
        for key, rec in fstate.edge_states(self.db, self.estate_id).items():
            fid, _, tid = key[len(fstate.EDGE_PREFIX):].partition("|")
            if fid in names and tid in names:
                out[(names[fid], names[tid])] = {"state": rec["state"], "reason": rec["reason"], "by": rec["by"] or "user", "when": rec["updated"], "snapshot": rec["snapshot_id"]}
        return out

    def set_edge_state(self, from_name: str, to_name: str, state: str, reason: str, by: str = "user") -> dict | None:
        ids = {v.lower(): k for k, v in self._model_names().items()}
        fid, tid = ids.get((from_name or "").lower()), ids.get((to_name or "").lower())
        if not fid or not tid:
            raise ValueError("both ends of a connection must be registered models")
        r = fstate.set_edge_state(self.db, self.estate_id, fid, tid, state, reason, by=self.user or (None if by in ("user", "chat") else by), snapshot_id=self.snapshot_id)
        return None if r is None else {"state": r["state"], "reason": r["reason"], "by": r["by"] or by, "when": r["updated"]}

    def size_states(self) -> dict:
        return fstate.size_states(self.db, self.estate_id)

    # ---------- the action plan (stage 4) ----------
    def action_states(self) -> dict:
        return fstate.action_states(self.db, self.estate_id)

    def set_action_state(self, key: str, state: str, reason: str, by: str = "user") -> dict:
        r = fstate.set_action_state(self.db, self.estate_id, key, state, reason, by=self.user or (None if by in ("user", "chat") else by), snapshot_id=self.snapshot_id)
        return {"key": r["key"], "state": r["state"], "reason": r["reason"], "by": r["by"] or by, "when": r["updated"]}

    def proposals(self) -> list[dict]:
        from . import plan as planmod
        return planmod.list_proposals(self.db, self.estate_id)

    def propose(self, title: str, why: str, steps: list[str], done_when: str, model: str, objects: list[str], citations: list[str], by: str = "chat") -> dict:
        """The chat tool's `propose_action`: kept beside the plan as the architect's suggestion, unconfirmed."""
        from . import plan as planmod
        return planmod.propose(self.db, self.estate_id, title, why, steps, done_when, model, objects, citations,
                               origin="chat_tool" if by == "chat" else "user", by=self.user, snapshot_id=self.snapshot_id)


def import_legacy_state(db: Db, estate_id: str, workspace_dir, model_id: str = "claude-sonnet-5") -> dict:
    """memories.json -> notes, statuses.json -> finding_state, transcripts/*.jsonl -> conversations. Once per estate."""
    import json
    from pathlib import Path
    from . import conversations as convs
    ws = Path(workspace_dir)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", estate_id)
    done = {"notes": 0, "statuses": 0, "conversations": 0}
    key = f"legacy_state_imported:{estate_id}"
    if db.one("SELECT 1 FROM settings WHERE workspace_id=? AND key=?", e["workspace_id"], key):
        return done
    mem = ws / "memories.json"
    if mem.is_file():
        try:
            for m in json.loads(mem.read_text(encoding="utf-8")):
                try:
                    notesmod.create(db, estate_id, m.get("text", ""), objects=[m.get("scope") or "estate"], type="conclusion",
                                    status="working_assumption", origin_kind="import", created=m.get("when"))
                    done["notes"] += 1
                except ValueError:
                    notesmod.create(db, estate_id, m.get("text", ""), objects=["estate"], type="conclusion", status="working_assumption",
                                    origin_kind="import", created=m.get("when"))
                    done["notes"] += 1
        except (OSError, json.JSONDecodeError):
            pass
    st = ws / "statuses.json"
    if st.is_file():
        try:
            for pid, rec in json.loads(st.read_text(encoding="utf-8")).items():
                if rec.get("status") in fstate.STATES:
                    fstate.set_state(db, estate_id, pid, rec["status"], rec.get("reason", ""), by=None)
                    done["statuses"] += 1
        except (OSError, json.JSONDecodeError):
            pass
    for p in sorted((ws / "transcripts").glob("*.jsonl")):
        if convs.import_transcript(db, estate_id, p, model_id):
            done["conversations"] += 1
    db.run("INSERT OR REPLACE INTO settings(workspace_id, key, value) VALUES (?,?,?)", e["workspace_id"], key, json.dumps(done))
    return done
