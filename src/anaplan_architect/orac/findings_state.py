"""Finding state: the owner's decision on a pattern (open, accepted, deliberate,
wont_fix, incorrect, fixed) and, since stage 4, on an action of the plan
(to_review, investigating, done, keep_current_design), with the reason, who
said so and on which snapshot. Replaces statuses.json.

One table, two key spaces: a pattern's key is its pattern id; an action's key is
`action:<candidate key>` for a deterministic card and `proposal:<id>` for one the
architect or the owner proposed. The material, the tools and the review read
pattern statuses only, so the action keys never leak into them.
"""
from __future__ import annotations
from .db import Db, now

STATES = ("open", "accepted", "deliberate", "wont_fix", "incorrect", "fixed", "to_review", "investigating", "done", "keep_current_design", "confirmed", "retired")
ACTION_STATES = ("to_review", "investigating", "done", "keep_current_design")
ACTION_PREFIXES = ("action:", "proposal:")
# Two more key spaces (the demo story, 2026-09-28): a connection between models (`edge:<from model id>|<to model id>`,
# confirmed or retired by the owner; no row means inferred from import names) and an over-dimensioned line item on the
# Size page (`size:<model>::<Module.Line Item>`, the action states). Both stay out of the pattern statuses.
EDGE_PREFIX = "edge:"
EDGE_STATES = ("confirmed", "retired")
SIZE_PREFIX = "size:"


def is_action_key(key: str) -> bool:
    return any((key or "").startswith(p) for p in ACTION_PREFIXES)


def is_edge_key(key: str) -> bool:
    return (key or "").startswith(EDGE_PREFIX)


def is_size_key(key: str) -> bool:
    return (key or "").startswith(SIZE_PREFIX)


def is_special_key(key: str) -> bool:
    """A key that is not a pattern id: never read as a pattern status."""
    return is_action_key(key) or is_edge_key(key) or is_size_key(key)


def edge_key(from_id: str, to_id: str) -> str:
    return f"{EDGE_PREFIX}{from_id}|{to_id}"


def size_key(model: str, ref: str) -> str:
    return f"{SIZE_PREFIX}{model}::{ref}"


def set_state(db: Db, eid: str, key: str, state: str, reason: str = "", by: str | None = None, snapshot_id: str | None = None) -> dict:
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    db.run("INSERT INTO finding_state(estate_id, finding_key, state, reason, author_id, snapshot_id, updated) VALUES (?,?,?,?,?,?,?) "
           "ON CONFLICT(estate_id, finding_key) DO UPDATE SET state=excluded.state, reason=excluded.reason, author_id=excluded.author_id, "
           "snapshot_id=excluded.snapshot_id, updated=excluded.updated", eid, key, state, (reason or "").strip(), by, snapshot_id, now())
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", eid)
    db.audit(e["workspace_id"], "action.state" if is_action_key(key) else "finding.state", key, {"estate": eid, "state": state, "reason": reason}, by)
    return get(db, eid, key)


def set_action_state(db: Db, eid: str, key: str, state: str, reason: str = "", by: str | None = None, snapshot_id: str | None = None) -> dict:
    """A decision on an action of the plan, or on an over-dimensioned line item of the Size page (key size:<model>::<ref>).
    It records the owner's word; it verifies nothing in Anaplan."""
    if not (is_action_key(key) or is_size_key(key)):
        raise ValueError("an action key starts with action:, proposal: or size:")
    if state not in ACTION_STATES:
        raise ValueError(f"state must be one of {ACTION_STATES}")
    return set_state(db, eid, key, state, reason, by=by, snapshot_id=snapshot_id)


def set_edge_state(db: Db, eid: str, from_id: str, to_id: str, state: str, reason: str = "", by: str | None = None, snapshot_id: str | None = None) -> dict | None:
    """The owner's word on a connection between two models: confirmed (the feed is real and used), retired (the import
    survives but the feed is dead), or inferred (back to what the import names say: the row goes)."""
    key = edge_key(from_id, to_id)
    if state == "inferred":
        clear(db, eid, key)
        return None
    if state not in EDGE_STATES:
        raise ValueError(f"state must be one of {EDGE_STATES + ('inferred',)}")
    return set_state(db, eid, key, state, reason, by=by, snapshot_id=snapshot_id)


def get(db: Db, eid: str, key: str) -> dict | None:
    return db.one("SELECT finding_key AS key, state, reason, author_id AS by, snapshot_id, updated FROM finding_state WHERE estate_id=? AND finding_key=?", eid, key)


def as_statuses(db: Db, eid: str) -> dict:
    """The shape the material, tools and review have always read: {pattern id: {status, reason, by, when}}. Action keys excluded."""
    return {r["finding_key"]: {"status": r["state"], "reason": r["reason"], "by": r["author_id"] or "user", "when": r["updated"], "snapshot": r["snapshot_id"]}
            for r in db.q("SELECT * FROM finding_state WHERE estate_id=?", eid) if not is_special_key(r["finding_key"])}


def action_states(db: Db, eid: str) -> dict:
    """{action:<key> | proposal:<id>: {state, reason, by, updated, snapshot_id}} for the plan."""
    return {r["finding_key"]: {"state": r["state"], "reason": r["reason"], "by": r["author_id"], "updated": r["updated"], "snapshot_id": r["snapshot_id"]}
            for r in db.q("SELECT * FROM finding_state WHERE estate_id=?", eid) if is_action_key(r["finding_key"])}


def edge_states(db: Db, eid: str) -> dict:
    """{edge:<from id>|<to id>: {state, reason, by, updated, snapshot_id}}; a connection with no row is inferred."""
    return {r["finding_key"]: {"state": r["state"], "reason": r["reason"], "by": r["author_id"], "updated": r["updated"], "snapshot_id": r["snapshot_id"]}
            for r in db.q("SELECT * FROM finding_state WHERE estate_id=?", eid) if is_edge_key(r["finding_key"])}


def size_states(db: Db, eid: str) -> dict:
    """{size:<model>::<Module.Line Item>: {state, reason, by, updated, snapshot_id}} for the Size page and the size tool."""
    return {r["finding_key"]: {"state": r["state"], "reason": r["reason"], "by": r["author_id"], "updated": r["updated"], "snapshot_id": r["snapshot_id"]}
            for r in db.q("SELECT * FROM finding_state WHERE estate_id=?", eid) if is_size_key(r["finding_key"])}


def clear(db: Db, eid: str, key: str) -> None:
    db.run("DELETE FROM finding_state WHERE estate_id=? AND finding_key=?", eid, key)
