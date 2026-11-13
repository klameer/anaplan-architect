"""Who may see which workspace (v0.2 P5). One login has many workspaces; a workspace is an isolated unit. Isolation is
in name only: one SQLite file, a membership row per (workspace, login), and one check, made here, that every request
goes through before its handler runs. A request that names a workspace, or anything that lives in one (a chat, an
upload, a model, a note, a document, an answer, a citation), is answered only to a member; to anyone else the thing
does not exist (404, never 403: the id is not confirmed).

In the store a workspace is an `estates` row (the name predates v0.2).
"""
from __future__ import annotations
from .db import Db, now

# the id in /api/<family>/<id>/... and how to find the workspace it lives in
LOOKUPS = {
    "conversations": "SELECT estate_id FROM conversations WHERE id=?",
    "snapshots": "SELECT estate_id FROM snapshots WHERE id=?",
    "models": "SELECT estate_id FROM models WHERE id=?",
    "notes": "SELECT estate_id FROM notes WHERE id=?",
    "documents": "SELECT estate_id FROM documents WHERE id=?",
    "turns": "SELECT c.estate_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?",
}
NOT_IDS = {"estates": {"create", "restore"}}
FAMILIES = ("estates", "citations", *LOOKUPS)


def estate_for(db: Db, path: str, live_citation=None) -> tuple[bool, str | None]:
    """(scoped, workspace id) for a request path. `scoped` is True when the path names something that lives in a
    workspace; the id is None when that thing is not in the store (the handler answers 404)."""
    parts = path.split("/")
    if len(parts) < 4 or parts[1] != "api" or parts[2] not in FAMILIES or not parts[3] or parts[3] in NOT_IDS.get(parts[2], ()):
        return False, None
    fam, ident = parts[2], parts[3]
    if fam == "estates":
        return True, ident
    if fam == "citations":
        row = db.one("SELECT c.estate_id FROM citations x JOIN turns t ON x.owner_kind='turn' AND t.id=x.owner_id JOIN conversations c ON c.id=t.conversation_id WHERE x.id=? LIMIT 1", ident) \
            or db.one("SELECT n.estate_id FROM citations x JOIN notes n ON x.owner_kind='note' AND n.id=x.owner_id WHERE x.id=? LIMIT 1", ident)
        if row:
            return True, row["estate_id"]
        return True, (live_citation(ident) if live_citation else None)
    row = db.one(LOOKUPS[fam], ident)
    return True, (row["estate_id"] if row else None)


def members(db: Db, eid: str) -> list[str]:
    return [r["user_id"] for r in db.q("SELECT user_id FROM estate_members WHERE estate_id=?", eid)]


def add_member(db: Db, eid: str, uid: str, role: str = "owner") -> None:
    db.run("INSERT OR IGNORE INTO estate_members(estate_id, user_id, role, added) VALUES (?,?,?,?)", eid, uid, role, now())


def is_member(db: Db, user: dict | None, eid: str) -> bool:
    """A member row, and nothing else. This only reads: memberships are written when a workspace is created or
    restored, when the first admin is created on a store that ran with no logins, and by the migrations."""
    if user is None:
        return False
    return db.one("SELECT 1 FROM estate_members WHERE estate_id=? AND user_id=?", eid, user["id"]) is not None


def adopt_orphans(db: Db, uid: str) -> int:
    """Workspaces nobody is a member of (made while the store ran with no logins) go to this login. Called once, when
    the first admin is created."""
    rows = db.q("SELECT id FROM estates WHERE id NOT IN (SELECT estate_id FROM estate_members)")
    for r in rows:
        add_member(db, r["id"], uid)
    return len(rows)


def visible(db: Db, user: dict | None, estates: list[dict]) -> list[dict]:
    """The workspaces of a list that this login is a member of."""
    if user is None:
        return estates
    return [e for e in estates if is_member(db, user, e["id"])]
