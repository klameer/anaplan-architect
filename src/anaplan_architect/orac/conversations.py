"""Conversations and turns in the store. The DB is the source of truth; the
JSONL transcript the Session still writes is the export kept beside it.
Every turn's citations are persisted (owner_kind 'turn') so a note saved
from an answer can point at the same evidence, and the verdict the answer
was given (what was cited, unchecked, unverified, phantom; which figures
traced) is kept beside them.

A conversation is held on the snapshot it started on (stage 5). When the
estate reads a newer snapshot the conversation is stale: the owner either
continues it on the held snapshot (recorded against the active snapshot of
the moment, so the question is asked once per activation) or re-evaluates it
on the current snapshot as a linked branch, a new conversation that carries
the same questions and points back at the original. The two are never mixed:
a held conversation answers from its own snapshot, a branch from the current
one, and each says which.
"""
from __future__ import annotations
import json, secrets
from pathlib import Path
from .db import Db, now


def _conv(db: Db, r: dict, with_turns: bool = False) -> dict:
    r["archived"] = bool(r["archived"])
    r["scope"] = json.loads(r.pop("scope_json") or "null") or {}
    agg = db.one("SELECT COUNT(*) AS turns, COALESCE(SUM(cost_usd),0) AS cost FROM turns WHERE conversation_id=?", r["id"])
    r["turns_count"] = agg["turns"]; r["cost_usd"] = round(agg["cost"], 4)
    r.setdefault("branched_from", None); r.setdefault("stale_ack_snapshot_id", None)
    r["branches"] = db.q("SELECT id, title, snapshot_id, created FROM conversations WHERE branched_from=? ORDER BY created", r["id"])
    r["origin"] = db.one("SELECT id, title, snapshot_id FROM conversations WHERE id=?", r["branched_from"]) if r["branched_from"] else None
    if with_turns:
        r["turns"] = [_turn(db, t) for t in db.q("SELECT * FROM turns WHERE conversation_id=? ORDER BY seq", r["id"])]
    return r


def stale(db: Db, c: dict, active_sid: str | None) -> dict | None:
    """None when the conversation is on the snapshot the estate reads; otherwise what the owner must decide:
    the snapshot it is held on (if the store still has it), the active one, and whether continuing was already
    acknowledged against this active snapshot."""
    held = c.get("snapshot_id")
    if not active_sid or held == active_sid:
        return None
    row = db.one("SELECT id, label, status, activated_at, superseded_at FROM snapshots WHERE id=?", held) if held else None
    return {"held_on": held, "held": row, "active": active_sid, "acked": c.get("stale_ack_snapshot_id") == active_sid, "can_continue": row is not None}


def ack_stale(db: Db, cid: str, active_sid: str, by: str | None = None) -> dict:
    """The owner chose to continue the conversation on the snapshot it is held on, knowing the estate reads another."""
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        raise KeyError(cid)
    db.run("UPDATE conversations SET stale_ack_snapshot_id=?, updated=? WHERE id=?", active_sid, now(), cid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "conversation.continue_on_snapshot", cid, {"held_on": r["snapshot_id"], "active": active_sid}, by)
    return get(db, cid, with_turns=False)


def branch(db: Db, cid: str, new_sid: str, by: str | None = None, title: str | None = None) -> tuple[dict, list[str]]:
    """A linked branch: a new conversation on the current snapshot with the same scope, pointing back at the
    original; the original's questions are returned so the caller can ask them again. No answer is copied:
    every claim in the branch is made against the snapshot it names."""
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        raise KeyError(cid)
    qs = [t["question"] for t in db.q("SELECT question FROM turns WHERE conversation_id=? ORDER BY seq", cid)]
    scope = json.loads(r["scope_json"] or "null") or None
    c = create(db, r["estate_id"], (title or r["title"] or "").strip()[:200], new_sid, author=by, scope=scope, branched_from=cid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "conversation.branch", c["id"], {"from": cid, "held_on": r["snapshot_id"], "on": new_sid, "questions": len(qs)}, by)
    return c, qs


def _turn(db: Db, t: dict) -> dict:
    out = {"id": t["id"], "seq": t["seq"], "q": t["question"], "a": t["answer"], "tools": json.loads(t["tools_json"] or "[]"),
           "usage": json.loads(t["usage_json"] or "{}"), "unverified": json.loads(t["unverified_json"] or "[]"),
           "unchecked": json.loads(t["unchecked_json"] or "[]"), "verification": json.loads(t.get("verification_json") or "null"),
           "when": t["created"], "by": t["author_id"], "mode": t.get("mode") or "full", "kind": t.get("kind") or "general",
           "context": json.loads(t.get("context_json") or "null"), "run": json.loads(t.get("run_json") or "null"),
           "blocks": json.loads(t.get("blocks_json") or "[]")}
    out["citations"] = [dict(json.loads(c["payload_json"] or "{}"), id=c["id"], kind=c["kind"], model=c["model_id"], ref=c["object_ref"],
                             snapshot_id=c["snapshot_id"], provenance=c["provenance"], tool=c["source_ref"])
                        for c in db.q("SELECT * FROM citations WHERE owner_kind='turn' AND owner_id=?", t["id"])]
    return out


def create(db: Db, eid: str, title: str, snapshot_id: str | None, author: str | None = None, scope: dict | None = None,
           transcript_path: str | None = None, cid: str | None = None, created: str | None = None, branched_from: str | None = None) -> dict:
    cid = cid or "c-" + secrets.token_hex(5)
    stamp = created or now()
    db.run("INSERT INTO conversations(id, estate_id, snapshot_id, title, author_id, created, updated, archived, scope_json, transcript_path, branched_from) "
           "VALUES (?,?,?,?,?,?,?,0,?,?,?)", cid, eid, snapshot_id, (title or "").strip()[:200], author, stamp, stamp,
           json.dumps(scope) if scope else None, str(transcript_path) if transcript_path else None, branched_from)
    return get(db, cid)


def get(db: Db, cid: str, with_turns: bool = True) -> dict:
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        raise KeyError(cid)
    return _conv(db, r, with_turns)


def list_conversations(db: Db, eid: str, q: str | None = None, archived: bool | None = False, limit: int = 500) -> list[dict]:
    where = ["estate_id=?"]; args: list = [eid]
    if archived is not None:
        where.append("archived=?"); args.append(1 if archived else 0)
    if q:
        where.append("(lower(title) LIKE ? OR id IN (SELECT conversation_id FROM turns WHERE lower(question) LIKE ? OR lower(answer) LIKE ?))")
        like = f"%{q.lower()}%"; args += [like, like, like]
    rows = db.q("SELECT * FROM conversations WHERE " + " AND ".join(where) + " ORDER BY updated DESC LIMIT ?", *args, limit)
    return [_conv(db, r) for r in rows]


def update(db: Db, cid: str, title: str | None = None, archived: bool | None = None, scope: dict | None = None, by: str | None = None) -> dict:
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        raise KeyError(cid)
    if title is not None and title.strip():
        db.run("UPDATE conversations SET title=? WHERE id=?", title.strip()[:200], cid)
    if archived is not None:
        db.run("UPDATE conversations SET archived=? WHERE id=?", 1 if archived else 0, cid)
    if scope is not None:
        db.run("UPDATE conversations SET scope_json=? WHERE id=?", json.dumps(scope) if scope else None, cid)
    db.run("UPDATE conversations SET updated=? WHERE id=?", now(), cid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "conversation.update", cid, {"title": title, "archived": archived, "scope": scope}, by)
    return get(db, cid, with_turns=False)


def add_turn(db: Db, cid: str, turn: dict, author: str | None = None, snapshot_id: str | None = None) -> dict:
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        raise KeyError(cid)
    seq = (db.one("SELECT COALESCE(MAX(seq), 0) AS s FROM turns WHERE conversation_id=?", cid) or {}).get("s", 0) + 1
    tid = "t-" + secrets.token_hex(5)
    usage = turn.get("usage") or {}
    ver = turn.get("verification")
    with db.tx():
        js = lambda v: json.dumps(v, default=str, ensure_ascii=False) if v is not None else None
        db.run("INSERT INTO turns(id, conversation_id, seq, author_id, question, answer, tools_json, usage_json, cost_usd, unverified_json, unchecked_json, "
               "verification_json, created, context_json, run_json, blocks_json, mode, kind, metered_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", tid, cid, seq, author or turn.get("by"),
               turn.get("q", ""), turn.get("a", ""),
               json.dumps(turn.get("tools") or [], default=str), json.dumps(usage, default=str), float(usage.get("cost_usd") or 0),
               json.dumps(turn.get("unverified") or []), json.dumps(turn.get("unchecked") or []),
               json.dumps(ver, default=str) if ver is not None else None, turn.get("when") or now(),
               js(turn.get("context")), js(turn.get("run")), js(turn.get("blocks")), turn.get("mode") or "full", turn.get("kind") or "general",
               float(usage.get("metered_usd") if usage.get("metered_usd") is not None else usage.get("cost_usd") or 0))
        for c in turn.get("citations") or []:
            db.run("INSERT OR IGNORE INTO citations(id, owner_kind, owner_id, provenance, snapshot_id, model_id, kind, object_ref, source_ref, payload_json) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", c.get("id"), "turn", tid, c.get("provenance") or "observed", c.get("snapshot_id") or snapshot_id or r["snapshot_id"],
                   c.get("model"), c.get("kind"), c.get("ref") or c.get("name") or "", c.get("tool"),
                   json.dumps({"name": c.get("name"), "as_written": c.get("as_written"), **({"quotes": c["quotes"]} if c.get("quotes") else {})}))
        db.run("UPDATE conversations SET updated=? WHERE id=?", now(), cid)
    return _turn(db, db.one("SELECT * FROM turns WHERE id=?", tid))


def delete(db: Db, cid: str, by: str | None = None) -> dict | None:
    r = db.one("SELECT * FROM conversations WHERE id=?", cid)
    if not r:
        return None
    with db.tx():
        db.run("DELETE FROM citations WHERE owner_kind='turn' AND owner_id IN (SELECT id FROM turns WHERE conversation_id=?)", cid)
        db.run("DELETE FROM conversations WHERE id=?", cid)
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", r["estate_id"])
    db.audit(e["workspace_id"], "conversation.delete", cid, None, by)
    return r


def _verdict(v: dict | None) -> str:
    if not v:
        return "Not checked (recorded before answers were verified)."
    fig = v.get("figures") or {}
    parts = [f"{v.get('cited', 0)} cited", f"{v.get('unchecked', 0)} unchecked", f"{v.get('unverified', 0)} not found"]
    if v.get("phantom"):
        parts.append(f"{len(v['phantom'])} phantom id(s): " + ", ".join(v["phantom"]))
    parts.append(f"figures {fig.get('traced', 0)} traced, {fig.get('derived', 0)} derived, {len(fig.get('untraced') or [])} untraced"
                 + (": " + ", ".join(fig["untraced"]) if fig.get("untraced") else ""))
    return "Checked: " + "; ".join(parts) + "."


def export_markdown(db: Db, cid: str) -> str:
    c = get(db, cid)
    out = [f"# {c['title'] or c['id']}", "", f"Estate {c['estate_id']} · snapshot {c['snapshot_id'] or 'unknown'} · started {c['created']} · {c['turns_count']} turn(s)"
           + (f" · re-evaluation of {c['branched_from']}" + (f" (held on snapshot {c['origin']['snapshot_id']})" if c.get("origin") else " (since deleted)") if c.get("branched_from") else "")
           + (" · re-evaluated as " + ", ".join(b["id"] for b in c["branches"]) if c.get("branches") else ""), ""]
    for t in c["turns"]:
        out += [f"## {t['seq']}. {t['q']}", "", t["a"], ""]
        if t["tools"]:
            out.append("Tools: " + ", ".join(x.get("tool", "") for x in t["tools"]))
        if t["citations"]:
            out.append("Cited: " + ", ".join(f"`{x.get('ref')}` ({x.get('id')})" for x in t["citations"]))
        if t["unverified"]:
            out.append("Not found in the estate: " + ", ".join(t["unverified"]))
        out.append(_verdict(t.get("verification")))
        out.append("")
    return "\n".join(out)


def export_jsonl(db: Db, cid: str) -> str:
    c = get(db, cid)
    lines = [json.dumps({"role": "title", "text": c["title"], "snapshot": c["snapshot_id"], "id": c["id"], "when": c["created"]}, ensure_ascii=False)]
    for t in c["turns"]:
        lines.append(json.dumps({"role": "user", "text": t["q"], "when": t["when"]}, ensure_ascii=False))
        lines.append(json.dumps({"role": "assistant", "text": t["a"], "tools": t["tools"], "unverified_names": t["unverified"], "unchecked": t["unchecked"],
                                 "citations": t["citations"], "verification": t.get("verification"), "usage": t["usage"], "user": t["by"], "when": t["when"]},
                                ensure_ascii=False, default=str))
    return "\n".join(lines) + "\n"


def import_transcript(db: Db, eid: str, path: str | Path, model_id: str = "claude-sonnet-5") -> dict | None:
    """One pre-store JSONL transcript becomes a conversation with its turns. Keyed by the file stem; runs once."""
    from ..chat import read_transcript, transcript_turns
    path = Path(path)
    cid = path.stem
    if db.one("SELECT 1 FROM conversations WHERE id=?", cid):
        return None
    recs = read_transcript(path)
    head = next((r for r in recs if r.get("role") == "title"), {})
    title = head.get("text") or next((r["text"] for r in recs if r.get("role") == "user"), "") or cid
    created = recs[0].get("when") if recs else None
    c = create(db, eid, title, head.get("snapshot"), author=None, transcript_path=path, cid=cid, created=created)
    for t in transcript_turns(recs, model_id):
        add_turn(db, cid, t, author=t.get("by"), snapshot_id=head.get("snapshot"))
    db.run("UPDATE conversations SET updated=? WHERE id=?", created or now(), cid)
    return get(db, c["id"], with_turns=False)
