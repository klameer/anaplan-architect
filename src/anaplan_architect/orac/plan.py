"""The action plan (Orac stage 4): the candidates anaplan-estate picks from the results of
every test (the plan is the first few that met the bar; the rest are kept with the reason
they are not on it), each carrying the owner's state and reasoning from the store, beside the
proposals the architect made in conversation or the owner typed. The two are kept
apart and labelled: a deterministic card rests on findings observed in the exports;
a proposal is a suggestion with no state until the owner records one. Nothing here
changes Anaplan. A state is a decision recorded, not a verification.
"""
from __future__ import annotations
import json, secrets
from anaplan_estate import plan as eplan
from .db import Db, now
from .evidence import Evidence
from . import findings_state as fstate
from . import checks as checksmod
from .objects import find_model

ORIGINS = ("chat_tool", "user")


def deterministic(er) -> dict:
    """anaplan-estate's selection over this parse. `actions` is the plan: the first few candidates that met the bar, a
    prerequisite before the action that needs it. `rest` is everything else, each with the reason it is not on the plan.
    `candidates` is both, in rank order: what a decision can be recorded on."""
    return eplan.select(er)


def _citer(snapshot_id: str | None):
    ev = Evidence("", snapshot_id or "")
    return lambda kind, model, ref: ev.mint(kind, model, ref).id


def resolve_objects(er, model: str, objects: list[str], cite) -> list[dict]:
    """Each named object as a chip: a line item when 'Module.Line Item' is one, a module when the name is one, else unknown."""
    m = find_model(er, model)
    out = []
    for o in objects or []:
        o = str(o).strip().strip("`").strip("'")
        if not o:
            continue
        if m is not None:
            key = next((k for k in m.model.line_items if f"{k[0]}.{k[1]}" == o), None) or next((k for k in m.model.line_items if f"{k[0]}.{k[1]}".lower() == o.lower()), None)
            if key is not None:
                out.append({"ref": f"{key[0]}.{key[1]}", "kind": "line_item", "model": m.name, "id": cite("line_item", m.name, f"{key[0]}.{key[1]}")}); continue
            mod = o if o in m.model.modules else next((x for x in m.model.modules if x.lower() == o.lower()), None)
            if mod is not None:
                out.append({"ref": mod, "kind": "module", "model": m.name, "id": cite("module", m.name, mod)}); continue
        out.append({"ref": o, "kind": None, "model": model, "id": None})
    return out


def check_objects(er, model: str, objects: list[str]) -> list[str]:
    """Canonical names, or ValueError naming what the model does not contain."""
    m = find_model(er, model)
    if m is None:
        raise ValueError(f"no model named {model!r}")
    res = resolve_objects(er, m.name, objects, lambda k, mdl, r: "")
    bad = [r["ref"] for r in res if r["kind"] is None]
    if bad:
        raise ValueError(f"not in {m.name}: " + ", ".join(bad))
    return [r["ref"] for r in res]


def cards(er, sel: dict, snapshot_id: str | None, states: dict) -> list[dict]:
    """Every candidate with the owner's state, its objects and findings as chips, and the explorer selection. `on_plan`
    says whether it is one of the plan's actions or listed under it with the reason (`why_not`)."""
    cite = _citer(snapshot_id)
    fmap = {f.id: f for f in er.findings}
    plan = {c["key"] for c in sel["actions"]}
    out = []
    for c in sel["candidates"]:
        d = dict(c)
        d["on_plan"] = c["key"] in plan
        d["tests_named"] = checksmod.named(c.get("tests"))      # the tests this action answers, by number and title
        st = states.get("action:" + c["key"])
        d["state"] = dict(st, default=False) if st else {"state": "to_review", "reason": "", "by": None, "updated": None, "snapshot_id": None, "default": True}
        d["state_key"] = "action:" + c["key"]
        d["provenance"] = "observed"
        d["objects_resolved"] = resolve_objects(er, c["model"], c["objects"][:40], cite)
        d["model_id"] = cite("model", c["model"], c["model"])
        d["findings"] = [{"id": fid, "title": fmap[fid].title, "area": fmap[fid].area, "strength": fmap[fid].strength, "importance": fmap[fid].importance,
                          "rules": [{"ref": r, "id": cite("finding", "", r)} for r in fmap[fid].rules]} for fid in c["finding_ids"] if fid in fmap]
        ex = c.get("explorer")
        if ex and isinstance(ex, (list, tuple)) and len(ex) == 3 and 0 <= ex[0] < len(er.models):
            mname = er.models[ex[0]].name
            d["explorer"] = {"model": mname, "module": ex[1], "name": ex[2], "ref": f"{ex[1]}.{ex[2]}" if ex[2] else ex[1], "kind": "line_item" if ex[2] else "module"}
        else:
            d["explorer"] = None
        out.append(d)
    return out


# ---------- proposals ----------

def _proposal(db: Db, r: dict) -> dict:
    r = dict(r)
    r["steps"] = json.loads(r.pop("steps_json") or "[]")
    r["objects"] = json.loads(r.pop("objects_json") or "[]")
    r["citations"] = json.loads(r.pop("citations_json") or "[]")
    r["withdrawn"] = bool(r.get("withdrawn_at"))
    return r


def propose(db: Db, eid: str, title: str, why: str = "", steps: list[str] | None = None, done_when: str = "", model: str = "", objects: list[str] | None = None,
            citations: list[str] | None = None, origin: str = "chat_tool", by: str | None = None, snapshot_id: str | None = None,
            conversation_id: str | None = None, turn_id: str | None = None) -> dict:
    if origin not in ORIGINS:
        raise ValueError(f"origin must be one of {ORIGINS}")
    title = (title or "").strip()
    if not title:
        raise ValueError("a proposal needs a title")
    pid = "p-" + secrets.token_hex(5)
    db.run("INSERT INTO proposals(id, estate_id, snapshot_id, title, why, steps_json, done_when, model, objects_json, citations_json, origin_kind, author_id, "
           "conversation_id, turn_id, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           pid, eid, snapshot_id, title, (why or "").strip(), json.dumps([s.strip() for s in (steps or []) if s and s.strip()], ensure_ascii=False),
           (done_when or "").strip(), model or "", json.dumps(list(objects or []), ensure_ascii=False), json.dumps(list(citations or []), ensure_ascii=False),
           origin, by, conversation_id, turn_id, now())
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", eid)
    db.audit(e["workspace_id"], "proposal.create", pid, {"estate": eid, "title": title, "origin": origin}, by)
    return get_proposal(db, pid)


def get_proposal(db: Db, pid: str) -> dict:
    r = db.one("SELECT * FROM proposals WHERE id=?", pid)
    if not r:
        raise KeyError(pid)
    return _proposal(db, r)


def list_proposals(db: Db, eid: str, withdrawn: bool = False) -> list[dict]:
    rows = db.q("SELECT * FROM proposals WHERE estate_id=? " + ("" if withdrawn else "AND withdrawn_at IS NULL ") + "ORDER BY created DESC", eid)
    return [_proposal(db, r) for r in rows]


def withdraw(db: Db, pid: str, by: str | None = None) -> dict:
    p = get_proposal(db, pid)
    if not p["withdrawn"]:
        db.run("UPDATE proposals SET withdrawn_at=?, withdrawn_by=? WHERE id=?", now(), by, pid)
        e = db.one("SELECT workspace_id FROM estates WHERE id=?", p["estate_id"])
        db.audit(e["workspace_id"], "proposal.withdraw", pid, {"estate": p["estate_id"]}, by)
    return get_proposal(db, pid)


def proposals_with_state(db: Db, eid: str, er, snapshot_id: str | None, states: dict, withdrawn: bool = False) -> list[dict]:
    cite = _citer(snapshot_id)
    out = []
    for p in list_proposals(db, eid, withdrawn=withdrawn):
        st = states.get("proposal:" + p["id"])
        p["state"] = dict(st, default=False) if st else None          # None: the owner has not taken it on
        p["state_key"] = "proposal:" + p["id"]
        p["provenance"] = "ai_proposed" if p["origin_kind"] == "chat_tool" else "not_established"
        p["objects_resolved"] = resolve_objects(er, p["model"], p["objects"], cite) if er is not None else []
        p["model_id"] = cite("model", p["model"], p["model"]) if p["model"] else None
        out.append(p)
    return out


def assemble(db: Db, eid: str, er, snapshot_id: str | None, sel: dict | None = None) -> dict:
    """Everything the Action plan page shows."""
    sel = sel or deterministic(er)
    states = fstate.action_states(db, eid)
    acts = cards(er, sel, snapshot_id, states)
    props = proposals_with_state(db, eid, er, snapshot_id, states)
    tally = {s: 0 for s in fstate.ACTION_STATES}
    for a in acts:
        tally[a["state"]["state"]] += 1
    for p in props:
        if p["state"]:
            tally[p["state"]["state"]] += 1
    return {"actions": acts, "proposals": props, "top": sel["top"], "on_plan": len(sel["actions"]), "ranking": sel["ranking"], "worth": sel["worth"],
            "considered": sel["considered"], "met_bar": sel["met_bar"], "none": sel["none"], "states": list(fstate.ACTION_STATES),
            "tally": tally, "unconfirmed": sum(1 for p in props if not p["state"]), "snapshot": snapshot_id,
            "limits": ["Marking an action done records a decision. It does not verify anything in Anaplan.",
                       "A proposal from the architect is a suggestion over the evidence it cites; it carries no state until the owner takes it on."]}


def valid_keys(db: Db, eid: str, sel: dict) -> set[str]:
    return {"action:" + c["key"] for c in sel["candidates"]} | {"proposal:" + p["id"] for p in list_proposals(db, eid)}
