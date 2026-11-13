"""The register: estates and the models in them, with purpose, owner, aliases
(phrases import action names use for the model) and a retired flag. Nothing
here reads an export; snapshots.py does that.
"""
from __future__ import annotations
import json, re, secrets, sqlite3
from .db import Db, now, new_id

_SAFE = re.compile(r"[^A-Za-z0-9 &()_.#'+-]+")


def safe_name(s: str) -> str:
    """A model name doubles as a folder name when the snapshot is materialised."""
    return _SAFE.sub("", (s or "")).strip()[:80].strip(" .")


def default_workspace(db: Db) -> str:
    """Until identity lands there is one workspace, 'local'. Created on first use."""
    row = db.one("SELECT id FROM workspaces ORDER BY created LIMIT 1")
    if row:
        return row["id"]
    db.run("INSERT INTO workspaces(id, name, created) VALUES (?,?,?)", "local", "This server", now())
    return "local"


# ---------- estates ----------

def create_estate(db: Db, workspace_id: str, name: str, created_by: str | None = None, estate_id: str | None = None, created: str | None = None) -> dict:
    eid = estate_id or new_id()
    name = (name or "").strip() or "Untitled estate"
    db.run("INSERT INTO estates(id, workspace_id, name, created_by, created) VALUES (?,?,?,?,?)", eid, workspace_id, name, created_by, created or now())
    db.audit(workspace_id, "estate.create", eid, {"name": name}, created_by)
    return get_estate(db, eid)


def get_estate(db: Db, eid: str) -> dict | None:
    row = db.one("SELECT * FROM estates WHERE id=?", eid)
    if row:
        row["archived"] = bool(row["archived"])
    return row


def list_estates(db: Db, workspace_id: str, include_archived: bool = False) -> list[dict]:
    rows = db.q("SELECT * FROM estates WHERE workspace_id=? " + ("" if include_archived else "AND archived=0 ") + "ORDER BY created", workspace_id)
    for r in rows:
        r["archived"] = bool(r["archived"])
    return rows


def update_estate(db: Db, eid: str, name: str | None = None, archived: bool | None = None) -> dict:
    e = get_estate(db, eid)
    if not e:
        raise KeyError(eid)
    if name is not None and name.strip():
        db.run("UPDATE estates SET name=? WHERE id=?", name.strip(), eid)
    if archived is not None:
        db.run("UPDATE estates SET archived=? WHERE id=?", 1 if archived else 0, eid)
    db.audit(e["workspace_id"], "estate.update", eid, {"name": name, "archived": archived})
    return get_estate(db, eid)


def delete_estate(db: Db, eid: str) -> None:
    """Rows only (models, aliases, snapshots, files and runs cascade). Materialised folders are the caller's."""
    e = get_estate(db, eid)
    if not e:
        return
    with db.tx():
        db.run("DELETE FROM estates WHERE id=?", eid)
    db.audit(e["workspace_id"], "estate.delete", eid)


# ---------- models ----------

def _with_aliases(db: Db, row: dict) -> dict:
    row["aliases"] = [a["alias"] for a in db.q("SELECT alias FROM model_aliases WHERE model_id=? ORDER BY alias", row["id"])]
    row["retired"] = bool(row["retired"])
    return row


def get_model(db: Db, mid: str) -> dict | None:
    row = db.one("SELECT * FROM models WHERE id=?", mid)
    return _with_aliases(db, row) if row else None


def list_models(db: Db, eid: str, include_retired: bool = True) -> list[dict]:
    rows = db.q("SELECT * FROM models WHERE estate_id=? " + ("" if include_retired else "AND retired=0 ") + "ORDER BY seq, created", eid)
    return [_with_aliases(db, r) for r in rows]


def find_model(db: Db, eid: str, name: str) -> dict | None:
    """By name, then by alias, case-insensitive; then by the folder-cleaned form of the name."""
    n = (name or "").strip()
    if not n:
        return None
    row = db.one("SELECT * FROM models WHERE estate_id=? AND lower(name)=lower(?)", eid, n)
    if not row:
        row = db.one("SELECT m.* FROM models m JOIN model_aliases a ON a.model_id=m.id WHERE m.estate_id=? AND lower(a.alias)=lower(?)", eid, n)
    if not row:
        from anaplan_estate.fleet import clean_name
        row = db.one("SELECT * FROM models WHERE estate_id=? AND lower(name)=lower(?)", eid, clean_name(n))
    return _with_aliases(db, row) if row else None


def add_model(db: Db, eid: str, name: str, purpose: str = "", owner: str = "", aliases=(), created_by: str | None = None, created: str | None = None) -> dict:
    e = get_estate(db, eid)
    if not e:
        raise KeyError(eid)
    n = safe_name(name)
    if not n:
        raise ValueError("model name is empty after removing characters a folder name cannot hold")
    if db.one("SELECT 1 FROM models WHERE estate_id=? AND lower(name)=lower(?)", eid, n):
        raise ValueError(f"a model named {n!r} already exists in this estate")
    mid = "m-" + secrets.token_hex(4)
    with db.tx():
        seq = (db.one("SELECT COALESCE(MAX(seq), 0) AS s FROM models WHERE estate_id=?", eid) or {}).get("s", 0) + 1
        db.run("INSERT INTO models(id, estate_id, name, purpose, owner, created_by, created, seq) VALUES (?,?,?,?,?,?,?,?)",
               mid, eid, n, (purpose or "").strip(), (owner or "").strip(), created_by, created or now(), seq)
        for a in aliases or ():
            a = (a or "").strip()
            if a:
                db.run("INSERT OR IGNORE INTO model_aliases(model_id, alias) VALUES (?,?)", mid, a)
    db.audit(e["workspace_id"], "model.add", mid, {"estate": eid, "name": n}, created_by)
    return get_model(db, mid)


def update_model(db: Db, mid: str, name: str | None = None, purpose: str | None = None, owner: str | None = None,
                 aliases=None, retired: bool | None = None, by: str | None = None) -> dict:
    m = get_model(db, mid)
    if not m:
        raise KeyError(mid)
    renamed = None
    with db.tx():
        if name is not None:
            n = safe_name(name)
            if not n:
                raise ValueError("model name is empty after removing characters a folder name cannot hold")
            if db.one("SELECT 1 FROM models WHERE estate_id=? AND lower(name)=lower(?) AND id<>?", m["estate_id"], n, mid):
                raise ValueError(f"a model named {n!r} already exists in this estate")
            db.run("UPDATE models SET name=? WHERE id=?", n, mid)
            if n != m["name"]:
                renamed = rename_state(db, m["estate_id"], m["name"], n)
        if purpose is not None:
            db.run("UPDATE models SET purpose=? WHERE id=?", purpose.strip(), mid)
        if owner is not None:
            db.run("UPDATE models SET owner=? WHERE id=?", owner.strip(), mid)
        if retired is not None:
            db.run("UPDATE models SET retired=? WHERE id=?", 1 if retired else 0, mid)
        if aliases is not None:
            db.run("DELETE FROM model_aliases WHERE model_id=?", mid)
            for a in aliases:
                a = (a or "").strip()
                if a:
                    db.run("INSERT OR IGNORE INTO model_aliases(model_id, alias) VALUES (?,?)", mid, a)
    e = get_estate(db, m["estate_id"])
    db.audit(e["workspace_id"], "model.update", mid, {"name": name, "purpose": purpose, "owner": owner, "aliases": aliases, "retired": retired,
                                                     "renamed": renamed}, by)
    return get_model(db, mid)


def rename_state(db: Db, eid: str, old: str, new: str) -> dict:
    """Every record that names a model by its text follows a rename, inside the caller's transaction: pattern statuses
    (<model>::<rule>::<label>), size decisions (size:<model>::<ref>) and action-plan states (action:<kind>:<model>[:<rest>])
    in finding_state; the model a proposal names; the citations the estate's turns and notes own (the model column, and
    the ref and name of a citation to the model itself or to one of its patterns); the model a conversation is scoped to.
    Ids, transcripts and answer text are left as they are: a citation id is the handle an answer was given, and it still
    opens, now under the new name. Returns how many rows each space rewrote."""
    from . import findings_state as fstate
    counts = {"finding_state": 0, "proposals": 0, "citations": 0, "conversations": 0}
    for r in db.q("SELECT id, finding_key FROM finding_state WHERE estate_id=?", eid):
        k = r["finding_key"]; nk = None
        if k.startswith(fstate.SIZE_PREFIX):
            if k.startswith(fstate.SIZE_PREFIX + old + "::"):
                nk = fstate.SIZE_PREFIX + new + k[len(fstate.SIZE_PREFIX + old):]
        elif k.startswith("action:"):
            kind, _, tail = k[len("action:"):].partition(":")
            if tail == old or tail.startswith(old + ":"):
                nk = f"action:{kind}:{new}{tail[len(old):]}"
        elif not fstate.is_special_key(k) and k.startswith(old + "::"):
            nk = new + k[len(old):]
        if nk:
            try:
                db.run("UPDATE finding_state SET finding_key=? WHERE id=?", nk, r["id"])
            except sqlite3.IntegrityError:            # a row already sits under the new key: that decision stands, the old one goes
                db.run("DELETE FROM finding_state WHERE id=?", r["id"])
            counts["finding_state"] += 1
    counts["proposals"] = db.run("UPDATE proposals SET model=? WHERE estate_id=? AND model=?", new, eid, old).rowcount
    owned = ("((owner_kind='turn' AND owner_id IN (SELECT t.id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=?)) "
             "OR (owner_kind='note' AND owner_id IN (SELECT id FROM notes WHERE estate_id=?)))")
    rows = db.q(f"SELECT id, owner_kind, owner_id, kind, model_id, object_ref, payload_json FROM citations WHERE {owned} "
                "AND (model_id=? OR (kind='model' AND object_ref=?) OR (kind='pattern' AND object_ref LIKE ?))", eid, eid, old, old, old + "::%")
    for c in rows:
        ref = c["object_ref"]
        if c["kind"] == "model" and ref == old:
            ref = new
        elif c["kind"] == "pattern" and ref.startswith(old + "::"):
            ref = new + ref[len(old):]
        model = new if c["model_id"] == old else c["model_id"]
        if ref == c["object_ref"] and model == c["model_id"]:
            continue                                  # a LIKE match on a wildcard in the name, not this model
        payload = json.loads(c["payload_json"] or "{}") or {}
        if payload.get("name") == c["object_ref"]:
            payload["name"] = ref
        db.run("UPDATE citations SET model_id=?, object_ref=?, payload_json=? WHERE id=? AND owner_kind=? AND owner_id=?",
               model, ref, json.dumps(payload, ensure_ascii=False), c["id"], c["owner_kind"], c["owner_id"])
        counts["citations"] += 1
    for c in db.q("SELECT id, scope_json FROM conversations WHERE estate_id=? AND scope_json IS NOT NULL", eid):
        sc = json.loads(c["scope_json"] or "null") or {}
        if sc.get("model") == old:
            sc["model"] = new
            db.run("UPDATE conversations SET scope_json=? WHERE id=?", json.dumps(sc), c["id"])
            counts["conversations"] += 1
    return counts


def aliases_map(db: Db, eid: str) -> dict[str, str]:
    """alias phrase -> model name, as fleet.run wants it."""
    rows = db.q("SELECT a.alias, m.name FROM model_aliases a JOIN models m ON m.id=a.model_id WHERE m.estate_id=?", eid)
    return {r["alias"]: r["name"] for r in rows}
