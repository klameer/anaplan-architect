"""Freshness: what moved under the owner's evidence when the estate went to a
new snapshot.

A note carries citations bound to the snapshot they were read on. When another
snapshot is activated, each cited object is compared between that baseline and
the new snapshot: a line item's formula may have changed or the item may have
gone; a module may have lost or changed line items; a model, an action, a
pattern or a rule may have disappeared; a note cited by another may have been
superseded or deleted; the snapshot a citation was read on may itself be gone
from the store. Notes whose evidence moved are flagged for the owner's review.
Nothing is closed, rewritten or hidden from retrieval by this: the flag travels
with the note into the material, so the architect sees it too.

Line items and modules are compared with anaplan-grammar's diff layer
(`diff_models`), called once per model per pair of snapshots; the rest is an
existence check on the new snapshot. Marking a note reviewed records the
snapshot the owner reviewed against; the next activation compares from there,
so a change is raised once, not at every activation after it.
"""
from __future__ import annotations
import json
from .db import Db, now
from . import objects as objmod

STATES = ("unchanged", "changed", "gone", "renamed", "deleted", "superseded", "unknown")
FLAGGING = ("changed", "gone", "renamed", "deleted", "superseded")


def _n(x) -> int:
    return len(x) if isinstance(x, (list, tuple, set, dict)) else int(x or 0)


class Comparer:
    """Objects between two snapshots: each estate run loaded once, each model diffed once."""

    def __init__(self, snaps, old_sid: str, new_sid: str):
        self.snaps, self.old_sid, self.new_sid = snaps, old_sid, new_sid
        self._old = self._new = None
        self._diffs: dict[str, dict | None] = {}

    def runs(self):
        if self._new is None:
            self._new = self.snaps.estate_run(self.new_sid, block=True)     # activation waits for its own comparison
        if self._old is None:
            self._old = self.snaps.estate_run(self.old_sid, block=True)
        return self._old, self._new

    def diff(self, model: str) -> dict | None:
        """Per model: line items changed / removed / renamed with their formulas, modules removed / changed.
        None when the model is not in both snapshots."""
        if model in self._diffs:
            return self._diffs[model]
        old, new = self.runs()
        a, b = objmod.find_model(old, model), objmod.find_model(new, model)
        out = None
        if a is not None and b is not None:
            from anaplan_grammar.diff import diff_models
            d = diff_models(a.model, b.model)
            out = {"li": {}, "renamed": {}, "mod": {}}
            for li in d.line_items:
                out["li"][f"{li.module}.{li.name}"] = li
                if getattr(li, "renamed_from", None):
                    out["renamed"][f"{li.module}.{li.renamed_from}"] = li
            for mo in d.modules:
                out["mod"][mo.name] = mo
        self._diffs[model] = out
        return out

    def compare(self, kind: str, model: str | None, ref: str) -> dict:
        """{status, was, now, detail}: was/now are formulas for a line item, nothing for the rest."""
        old, new = self.runs()
        r = {"status": "unknown", "was": None, "now": None, "detail": ""}
        if kind in ("line_item", "module"):
            if not model:
                model = objmod.guess(old, ref, None, kind)[1] or objmod.guess(new, ref, None, kind)[1]
            d = self.diff(model) if model else None
            if d is None:
                if model and objmod.find_model(new, model) is None:
                    r.update(status="gone", detail="the model is not in the new snapshot")
                else:
                    r.update(detail="the model was not in both snapshots")
                return r
            if kind == "line_item":
                li = d["li"].get(ref)
                if li is None:
                    ren = d["renamed"].get(ref)
                    if ren is not None:
                        r.update(status="renamed", now=f"{ren.module}.{ren.name}", was=ren.formula_before, detail=f"now named {ren.module}.{ren.name}")
                        return r
                    r["status"] = "unchanged"
                    return r
                if li.kind == "removed":
                    r.update(status="gone", was=li.formula_before, detail="not in the new snapshot")
                    return r
                if (li.formula_before or "") != (li.formula_after or ""):
                    r.update(status="changed", was=li.formula_before, now=li.formula_after, detail="formula changed")
                    return r
                fields = [getattr(f, "field", "") for f in (li.fields or []) if getattr(f, "field", "") != "Formula"]
                r.update(status="unchanged", detail=(", ".join(fields) + " changed; formula unchanged") if fields else "")
                return r
            mo = d["mod"].get(ref)
            if mo is None:
                r["status"] = "unchanged"
                return r
            if mo.kind == "removed":
                r.update(status="gone", detail="not in the new snapshot")
                return r
            add, rem, chg = _n(mo.line_items_added), _n(mo.line_items_removed), _n(mo.line_items_changed)
            if rem or chg:
                r.update(status="changed", detail=f"{chg} line item formula(s) changed, {rem} removed, {add} added")
            else:
                r.update(status="unchanged", detail=f"{add} line item(s) added" if add else "")
            return r
        if kind == "model":
            r["status"] = "unchanged" if objmod.find_model(new, ref) is not None else "gone"
            return r
        if kind in ("action", "pattern", "finding"):
            r["status"] = "unchanged" if objmod.resolve(new, kind, model, ref, self.new_sid) is not None else "gone"
            if r["status"] == "gone":
                r["detail"] = "not in the new snapshot"
            return r
        return r


def note_sources(db: Db, nid: str) -> list[dict]:
    """The citation rows behind a note's sources: the note's own copy first, else the turn's; an id no row
    records any more comes back with status 'deleted'."""
    out = []
    for s in db.q("SELECT citation_id FROM note_sources WHERE note_id=?", nid):
        row = db.one("SELECT * FROM citations WHERE id=? ORDER BY CASE owner_kind WHEN 'note' THEN 0 ELSE 1 END LIMIT 1", s["citation_id"])
        if row is None:
            out.append({"id": s["citation_id"], "kind": None, "model_id": None, "object_ref": None, "snapshot_id": None, "name": None, "missing": True})
            continue
        name = (json.loads(row["payload_json"] or "{}") or {}).get("name")
        out.append(dict(row, name=name, missing=False))
    return out


def check_source(db: Db, snaps, comparers: dict, s: dict, new_sid: str, baseline: str | None = None) -> dict:
    """One source against the new snapshot, compared from the baseline (the snapshot the owner last reviewed
    against) or, failing that, the snapshot the citation was read on."""
    item = {"id": s["id"], "kind": s.get("kind"), "model": s.get("model_id"), "ref": s.get("object_ref"), "name": s.get("name"),
            "snapshot_id": s.get("snapshot_id"), "status": "unknown", "was": None, "now": None, "detail": ""}
    if s.get("missing"):
        item.update(status="deleted", detail="no turn or note records this citation any more")
        return item
    if s.get("kind") == "note":
        n = db.one("SELECT status FROM notes WHERE id=?", s["object_ref"])
        item["status"] = "deleted" if not n else ("superseded" if n["status"] == "superseded" else "unchanged")
        item["detail"] = "the cited note was deleted" if not n else ("the cited note was superseded" if n["status"] == "superseded" else "")
        return item
    base = None
    for cand in (baseline, s.get("snapshot_id")):
        if cand and db.one("SELECT 1 FROM snapshots WHERE id=?", cand):
            base = cand
            break
    if base is None:
        item.update(status="deleted", detail="the snapshot it was read on is no longer in the store")
        return item
    if base == new_sid:
        item["status"] = "unchanged"
        return item
    cmp = comparers.get(base)
    if cmp is None:
        cmp = comparers[base] = Comparer(snaps, base, new_sid)
    try:
        item.update(cmp.compare(s.get("kind") or "", s.get("model_id"), s.get("object_ref") or ""))
    except Exception as ex:      # a snapshot that cannot be parsed any more is reported, never raised into activation
        item.update(status="unknown", detail=f"could not compare: {type(ex).__name__}: {ex}"[:300])
    return item


def review_notes(db: Db, snaps, eid: str, new_sid: str, by: str | None = None) -> dict:
    """After an activation: every current note that carries citations is checked against the new snapshot and
    flagged when its evidence moved. Returns what was flagged, for the page to say so."""
    rows = db.q("SELECT id, title, reviewed_snapshot_id, reviewed_at, review_json FROM notes WHERE estate_id=? AND status<>'superseded' "
                "AND EXISTS (SELECT 1 FROM note_sources s WHERE s.note_id=notes.id) ORDER BY created", eid)
    comparers: dict[str, Comparer] = {}
    out = {"snapshot": new_sid, "reviewed": 0, "flagged": 0, "notes": []}
    for n in rows:
        checked = [check_source(db, snaps, comparers, s, new_sid, baseline=n["reviewed_snapshot_id"]) for s in note_sources(db, n["id"])]
        # a source already seen as deleted or superseded when the owner last reviewed the note is not raised again
        prev = {s.get("id"): s.get("status") for s in ((json.loads(n["review_json"] or "null") or {}).get("sources") or [])} if n["reviewed_at"] else {}
        moved = [c for c in checked if c["status"] in FLAGGING and not (c["status"] in ("deleted", "superseded") and prev.get(c["id"]) == c["status"])]
        flag = None
        if moved:
            flag = "gone" if all(c["status"] in ("gone", "deleted", "superseded") for c in moved) else "changed"
        review = {"snapshot_id": new_sid, "at": now(), "sources": checked, "flag": flag,
                  "summary": ", ".join(f"{c['status']}: {c['ref'] or c['id']}" for c in moved)[:600]}
        db.run("UPDATE notes SET review_flag=?, review_json=? WHERE id=?", flag, json.dumps(review, ensure_ascii=False, default=str), n["id"])
        out["reviewed"] += 1
        if flag:
            out["flagged"] += 1
            out["notes"].append({"id": n["id"], "title": n["title"], "flag": flag, "summary": review["summary"]})
    e = db.one("SELECT workspace_id FROM estates WHERE id=?", eid)
    if e:
        db.audit(e["workspace_id"], "notes.review", new_sid, {"estate": eid, "reviewed": out["reviewed"], "flagged": out["flagged"]}, by)
    return out
