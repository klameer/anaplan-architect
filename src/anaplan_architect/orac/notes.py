"""Notes: what the owner has established about the estate, kept between
conversations and runs.

A note has a type (purpose, decision, constraint, procedure, conclusion), a
status (working assumption, user confirmed, superseded), one or more scopes
(the estate, a model, a module, a line item, a rule) and an origin (typed by
hand, saved from an answer, kept by the chat tool, imported). Two notes on the
same object that disagree both survive and both surface as siblings; nothing
here decides which is right, and nothing is auto-closed. Retrieval is FTS5
over title and body plus the scope: no embeddings, no ingest cost.
"""
from __future__ import annotations
import json, re, secrets
from .db import Db, now

TYPES = ("purpose", "decision", "constraint", "procedure", "conclusion")
STATUSES = ("working_assumption", "user_confirmed", "superseded")
SCOPES = ("estate", "model", "module", "line_item", "rule")
ORIGINS = ("user", "answer", "chat_tool", "import")


# a citation (alias x) that this workspace holds: on one of its answers or on one of its notes. Two parameters: the estate, twice.
_IN_ESTATE = ("((x.owner_kind='turn' AND x.owner_id IN (SELECT t.id FROM turns t JOIN conversations cv ON cv.id=t.conversation_id WHERE cv.estate_id=?)) "
              "OR (x.owner_kind='note' AND x.owner_id IN (SELECT id FROM notes WHERE estate_id=?)))")


def _row(db: Db, r: dict) -> dict:
    r["objects"] = db.q("SELECT o.scope, o.model_id, m.name AS model, o.module, o.line_item, o.rule FROM note_objects o "
                        "LEFT JOIN models m ON m.id=o.model_id AND m.estate_id=? WHERE o.note_id=? ORDER BY o.id", r["estate_id"], r["id"])
    r["sources"] = [x["citation_id"] for x in db.q("SELECT citation_id FROM note_sources WHERE note_id=?", r["id"])]
    r["sources_resolved"] = [dict(json.loads(c["payload_json"] or "{}") or {}, id=c["id"], kind=c["kind"], model=c["model_id"], ref=c["object_ref"],
                                  provenance=c["provenance"], snapshot_id=c["snapshot_id"], tool=c["source_ref"])
                             for c in db.q("SELECT c.* FROM note_sources s JOIN citations c ON c.id=s.citation_id WHERE s.note_id=? AND " + _IN_ESTATE.replace("x.", "c.") +
                                           " GROUP BY c.id ORDER BY c.kind, c.object_ref", r["id"], r["estate_id"], r["estate_id"])]
    seen = {c["id"] for c in r["sources_resolved"]}
    r["sources_missing"] = [x for x in r["sources"] if x not in seen]          # deleted, never recorded, or not of this workspace: all look the same
    r["scope_labels"] = [scope_label(o) for o in r["objects"]]
    r["review"] = json.loads(r.pop("review_json", None) or "null") if "review_json" in r else None
    return r


def scope_label(o: dict) -> str:
    s = o["scope"]
    if s == "estate":
        return "estate"
    if s == "model":
        return f"model:{o.get('model') or o.get('model_id')}"
    if s == "module":
        return f"{o.get('model') or ''}::{o.get('module')}".strip(":")
    if s == "line_item":
        return f"{o.get('model') or ''}::{o.get('module')}.{o.get('line_item')}".strip(":")
    return f"rule:{o.get('rule')}"


def normalise_objects(db: Db, eid: str, objects) -> list[dict]:
    """Accepts dicts {scope, model|model_id, module, line_item, rule} or strings 'estate' | 'model:Name' |
    'rule:ID' | 'Model::Module' | 'Model::Module.Line Item'. Unknown model names raise."""
    out = []
    for o in objects or []:
        if isinstance(o, str):
            o = parse_scope(o)
        scope = o.get("scope")
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of {SCOPES}")
        mid = o.get("model_id")
        if mid and not db.one("SELECT 1 FROM models WHERE id=? AND estate_id=?", mid, eid):       # a model of this workspace, or none
            raise ValueError("no such model in this workspace")
        if not mid and o.get("model"):
            row = db.one("SELECT id FROM models WHERE estate_id=? AND lower(name)=lower(?)", eid, o["model"])
            if not row:
                raise ValueError(f"no model named {o['model']!r} in this estate")
            mid = row["id"]
        if scope in ("model", "module", "line_item") and not mid:
            raise ValueError(f"a {scope} scope needs a model")
        if scope == "module" and not o.get("module"):
            raise ValueError("a module scope needs the module name")
        if scope == "line_item" and not (o.get("module") and o.get("line_item")):
            raise ValueError("a line item scope needs 'module' and 'line_item'")
        if scope == "rule" and not o.get("rule"):
            raise ValueError("a rule scope needs the rule id")
        out.append({"scope": scope, "model_id": mid if scope != "estate" and scope != "rule" else None,
                    "module": o.get("module") if scope in ("module", "line_item") else None,
                    "line_item": o.get("line_item") if scope == "line_item" else None,
                    "rule": o.get("rule") if scope == "rule" else None})
    return out or [{"scope": "estate", "model_id": None, "module": None, "line_item": None, "rule": None}]


def parse_scope(s: str) -> dict:
    s = (s or "").strip()
    if s in ("", "estate"):
        return {"scope": "estate"}
    if s.startswith("model:"):
        return {"scope": "model", "model": s[6:].strip()}
    if s.startswith("rule:"):
        return {"scope": "rule", "rule": s[5:].strip()}
    if "::" in s:
        model, _, rest = s.partition("::")
        if "." in rest:
            module, _, li = rest.partition(".")
            return {"scope": "line_item", "model": model.strip(), "module": module.strip(), "line_item": li.strip()}
        return {"scope": "module", "model": model.strip(), "module": rest.strip()}
    return {"scope": "model", "model": s}


def create(db: Db, eid: str, body: str, title: str = "", type: str = "conclusion", status: str = "working_assumption",
           objects=None, author: str | None = None, origin_kind: str = "user", origin_conversation_id: str | None = None,
           origin_turn_id: str | None = None, sources=(), created: str | None = None) -> dict:
    body = (body or "").strip()
    if not body:
        raise ValueError("a note needs a body")
    if type not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    if origin_kind not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}")
    objs = normalise_objects(db, eid, objects)
    nid = "n-" + secrets.token_hex(5)
    stamp = created or now()
    title = (title or "").strip()[:200] or body.splitlines()[0][:120]
    with db.tx():
        db.run("INSERT INTO notes(id, estate_id, title, body, type, status, author_id, confirmed_by, confirmed_at, created, updated, origin_kind, "
               "origin_conversation_id, origin_turn_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               nid, eid, title, body, type, status, author, author if status == "user_confirmed" else None,
               stamp if status == "user_confirmed" else None, stamp, stamp, origin_kind, origin_conversation_id, origin_turn_id)
        for o in objs:
            db.run("INSERT INTO note_objects(note_id, scope, model_id, module, line_item, rule) VALUES (?,?,?,?,?,?)",
                   nid, o["scope"], o["model_id"], o["module"], o["line_item"], o["rule"])
        for c in sources or ():
            # A source resolves only to a citation this workspace holds. An id from another workspace is kept as text
            # like any id that resolves to nothing: it is never copied, never opened, and looks no different from a made-up one.
            db.run("INSERT OR IGNORE INTO note_sources(note_id, citation_id) VALUES (?,?)", nid, c)
            # the note keeps its own copy of the citation, so the evidence survives the conversation it came from being deleted
            db.run("INSERT OR IGNORE INTO citations(id, owner_kind, owner_id, provenance, snapshot_id, model_id, kind, object_ref, source_ref, payload_json) "
                   "SELECT id, 'note', ?, provenance, snapshot_id, model_id, kind, object_ref, source_ref, payload_json FROM citations x WHERE x.id=? "
                   "AND ((x.owner_kind='turn' AND x.owner_id IN (SELECT t.id FROM turns t JOIN conversations cv ON cv.id=t.conversation_id WHERE cv.estate_id=?)) "
                   "OR (x.owner_kind='note' AND x.owner_id IN (SELECT id FROM notes WHERE estate_id=?))) "
                   "ORDER BY CASE owner_kind WHEN 'turn' THEN 0 ELSE 1 END LIMIT 1", nid, c, eid, eid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", eid)
    db.audit(e["workspace_id"], "note.create", nid, {"estate": eid, "type": type, "origin": origin_kind}, author)
    return get(db, nid)


def get(db: Db, nid: str) -> dict:
    r = db.one("SELECT * FROM notes WHERE id=?", nid)
    if not r:
        raise KeyError(nid)
    r = _row(db, r)
    r["siblings"] = siblings(db, nid)
    return r


def update(db: Db, nid: str, title: str | None = None, body: str | None = None, type: str | None = None, status: str | None = None,
           objects=None, by: str | None = None, reviewed_on: str | None = None) -> dict:
    """reviewed_on: the snapshot the estate reads now; a flagged note whose body or status the owner changes counts as
    reviewed against it, so the same change is not raised again at the next activation."""
    r = db.one("SELECT * FROM notes WHERE id=?", nid)
    if not r:
        raise KeyError(nid)
    if type is not None and type not in TYPES:
        raise ValueError(f"type must be one of {TYPES}")
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    objs = normalise_objects(db, r["estate_id"], objects) if objects is not None else None
    with db.tx():
        if title is not None:
            db.run("UPDATE notes SET title=? WHERE id=?", title.strip()[:200], nid)
        if body is not None:
            if not body.strip():
                raise ValueError("a note needs a body")
            db.run("UPDATE notes SET body=? WHERE id=?", body.strip(), nid)
        if type is not None:
            db.run("UPDATE notes SET type=? WHERE id=?", type, nid)
        if status is not None:
            db.run("UPDATE notes SET status=?, confirmed_by=?, confirmed_at=? WHERE id=?", status,
                   by if status == "user_confirmed" else r["confirmed_by"], now() if status == "user_confirmed" else r["confirmed_at"], nid)
            if status != "superseded":
                db.run("UPDATE notes SET superseded_by=NULL WHERE id=?", nid)
        if objs is not None:
            db.run("DELETE FROM note_objects WHERE note_id=?", nid)
            for o in objs:
                db.run("INSERT INTO note_objects(note_id, scope, model_id, module, line_item, rule) VALUES (?,?,?,?,?,?)",
                       nid, o["scope"], o["model_id"], o["module"], o["line_item"], o["rule"])
        if r.get("review_flag") and (body is not None or status is not None):
            db.run("UPDATE notes SET review_flag=NULL, reviewed_at=?, reviewed_by=?, reviewed_snapshot_id=COALESCE(?, reviewed_snapshot_id) WHERE id=?",
                   now(), by, reviewed_on, nid)
        db.run("UPDATE notes SET updated=? WHERE id=?", now(), nid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "note.update", nid, {"title": title is not None, "body": body is not None, "type": type, "status": status}, by)
    return get(db, nid)


def mark_reviewed(db: Db, nid: str, by: str | None = None) -> dict:
    """The owner has looked at what moved under the note and keeps it as it is. The snapshot the review was made
    against becomes the baseline for the next comparison."""
    r = db.one("SELECT * FROM notes WHERE id=?", nid)
    if not r:
        raise KeyError(nid)
    review = json.loads(r.get("review_json") or "null") or {}
    db.run("UPDATE notes SET review_flag=NULL, reviewed_at=?, reviewed_by=?, reviewed_snapshot_id=COALESCE(?, reviewed_snapshot_id) WHERE id=?",
           now(), by, review.get("snapshot_id"), nid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "note.reviewed", nid, {"snapshot": review.get("snapshot_id"), "flag": r.get("review_flag")}, by)
    return get(db, nid)


def supersede(db: Db, nid: str, by_note: str | None = None, by: str | None = None) -> dict:
    r = db.one("SELECT * FROM notes WHERE id=?", nid)
    if not r:
        raise KeyError(nid)
    if by_note and not db.one("SELECT 1 FROM notes WHERE id=? AND estate_id=?", by_note, r["estate_id"]):
        raise ValueError("the superseding note must be in the same estate")
    db.run("UPDATE notes SET status='superseded', superseded_by=?, updated=?, review_flag=NULL WHERE id=?", by_note, now(), nid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "note.supersede", nid, {"by_note": by_note}, by)
    return get(db, nid)


def delete(db: Db, nid: str, by: str | None = None) -> None:
    r = db.one("SELECT * FROM notes WHERE id=?", nid)
    if not r:
        raise KeyError(nid)
    with db.tx():
        db.run("UPDATE notes SET superseded_by=NULL WHERE superseded_by=?", nid)
        db.run("DELETE FROM notes WHERE id=?", nid)
        db.run("DELETE FROM citations WHERE owner_kind='note' AND owner_id=?", nid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "note.delete", nid, None, by)


def _fts_query(text: str, mode: str = "and") -> str:
    toks = [t for t in re.split(r"[^\w%&']+", (text or "").lower()) if len(t) >= 2][:24]
    if not toks:
        return ""
    quoted = ['"' + t.replace('"', '') + '"' + ("*" if mode == "and" else "") for t in toks]
    return (" AND " if mode == "and" else " OR ").join(quoted)


def list_notes(db: Db, eid: str, q: str | None = None, type: str | None = None, status: str | None = None, model_id: str | None = None,
               module: str | None = None, include_superseded: bool = False, limit: int = 200, flagged: bool = False) -> list[dict]:
    where = ["n.estate_id=?"]; args: list = [eid]
    if flagged:
        where.append("n.review_flag IS NOT NULL")
    if type:
        where.append("n.type=?"); args.append(type)
    if status:
        where.append("n.status=?"); args.append(status)
    elif not include_superseded:
        where.append("n.status<>'superseded'")
    if model_id:
        where.append("EXISTS (SELECT 1 FROM note_objects o WHERE o.note_id=n.id AND (o.model_id=? OR o.scope='estate'))"); args.append(model_id)
    if module:
        where.append("EXISTS (SELECT 1 FROM note_objects o WHERE o.note_id=n.id AND o.module=?)"); args.append(module)
    fq = _fts_query(q or "", "and")
    if fq:
        rows = db.q("SELECT n.*, bm25(notes_fts) AS rank FROM notes_fts JOIN notes n ON n.rowid=notes_fts.rowid WHERE notes_fts MATCH ? AND "
                    + " AND ".join(where) + " ORDER BY rank LIMIT ?", fq, *args, limit)
    else:
        rows = db.q("SELECT n.* FROM notes n WHERE " + " AND ".join(where) + " ORDER BY n.updated DESC LIMIT ?", *args, limit)
    return [_row(db, r) for r in rows]


def search(db: Db, eid: str, text: str, model_id: str | None = None, module: str | None = None, limit: int = 6) -> list[dict]:
    """Retrieval for a turn: current notes for the scope (estate-wide ones always), best matches to the
    question first, then the most recently updated. Any-token match, so recall beats precision."""
    fq = _fts_query(text, "or")
    # an unscoped conversation sees every current note; a scoped one sees the estate-wide notes plus its model's (and module's)
    if model_id:
        scope = "(o.scope='estate' OR o.model_id=? " + ("OR o.module=? " if module else "") + ")"
        args: list = [eid, model_id] + ([module] if module else [])
    else:
        scope = "1=1"
        args = [eid]
    base = ("FROM notes n WHERE n.estate_id=? AND n.status<>'superseded' AND EXISTS (SELECT 1 FROM note_objects o WHERE o.note_id=n.id AND " + scope + ")")
    out: list[dict] = []
    if fq:
        out = db.q("SELECT n.*, bm25(notes_fts) AS rank FROM notes_fts JOIN notes n ON n.rowid=notes_fts.rowid WHERE notes_fts MATCH ? AND n.estate_id=? "
                   "AND n.status<>'superseded' AND EXISTS (SELECT 1 FROM note_objects o WHERE o.note_id=n.id AND " + scope + ") ORDER BY rank LIMIT ?",
                   fq, *args, limit)
    if len(out) < limit:
        seen = {r["id"] for r in out}
        for r in db.q("SELECT n.* " + base + " ORDER BY n.updated DESC LIMIT ?", *args, limit):
            if r["id"] not in seen and len(out) < limit:
                out.append(r)
    return [_row(db, r) for r in out]


def siblings(db: Db, nid: str) -> list[dict]:
    """Other current notes that share an object with this one: where disagreements live."""
    rows = db.q("SELECT DISTINCT n.id, n.title, n.type, n.status, n.updated, substr(n.body, 1, 200) AS body FROM note_objects a "
                "JOIN note_objects b ON b.scope=a.scope AND COALESCE(b.model_id,'')=COALESCE(a.model_id,'') AND COALESCE(b.module,'')=COALESCE(a.module,'') "
                "AND COALESCE(b.line_item,'')=COALESCE(a.line_item,'') AND COALESCE(b.rule,'')=COALESCE(a.rule,'') "
                "JOIN notes n ON n.id=b.note_id WHERE a.note_id=? AND b.note_id<>? AND n.status<>'superseded' AND a.scope<>'estate' ORDER BY n.updated DESC", nid, nid)
    return rows


def as_memories(db: Db, eid: str) -> list[dict]:
    """Current notes in the shape the material and the chat tools have always read: {scope, text, by, when}."""
    out = []
    for n in list_notes(db, eid, include_superseded=False, limit=500):
        text = n["body"] if not n["title"] or n["body"].startswith(n["title"]) else f"{n['title']}: {n['body']}"
        flag = "; evidence it cites has changed since, under review" if n.get("review_flag") else ""
        tag = f"[{n['type']}, {'confirmed' if n['status'] == 'user_confirmed' else 'working assumption'}{flag}] "
        scopes = n["scope_labels"] or ["estate"]
        for s in scopes:
            out.append({"scope": s if not s.startswith("model:") and "::" not in s else ("model:" + s.split("::")[0] if "::" in s else s),
                        "text": tag + text, "by": n["author_id"] or n["origin_kind"], "when": n["updated"], "id": n["id"], "type": n["type"], "status": n["status"]})
    return out


def count(db: Db, eid: str) -> int:
    return db.one("SELECT COUNT(*) AS n FROM notes WHERE estate_id=? AND status<>'superseded'", eid)["n"]


def count_flagged(db: Db, eid: str) -> int:
    return db.one("SELECT COUNT(*) AS n FROM notes WHERE estate_id=? AND status<>'superseded' AND review_flag IS NOT NULL", eid)["n"]
