"""What a citation opens: the object behind an id, read from the snapshot the
id was minted on. A line item opens with its formula, dimensions, findings and
graph neighbours; a module with its line items and the modules either side of
it; a model with its facts and feeds; an action with its target and process; a
pattern and a rule with their text. Everything named here gets an id of its own,
bound to the same snapshot, so the reader can keep clicking through the estate.
The row of the export an object was read from comes from the snapshot's blob.
Notes are resolved by the web layer from the store, not here.
"""
from __future__ import annotations
from pathlib import Path
from .evidence import Evidence, NOTE_ID

ROW_KIND = {"line_item": "line_items", "module": "modules", "action": "actions"}
_MAX_ITEMS = 300


def find_model(er, name: str | None):
    if not name:
        return None
    for m in er.models:
        if m.name == name:
            return m
    for m in er.models:
        if m.name.lower() == name.lower():
            return m
    return None


def guess(er, ref: str, model: str | None = None, kind: str | None = None) -> tuple[str | None, str | None, str]:
    """(kind, model, canonical ref) for a name clicked or typed without an id: a note id, a pattern id, a rule id,
    a model, 'Module.Line Item', a module, an action or process, or a line-item name unique in one model.
    A kind, when the page knows it, narrows the search; a model, when known, scopes it; neither is required."""
    from anaplan_estate.lint import RULES
    ref = (ref or "").strip().strip("`").strip("'")
    any_kind = not kind
    if kind == "note" or (any_kind and NOTE_ID.fullmatch(ref)):
        return "note", None, ref
    if kind == "pattern" or (any_kind and ref.count("::") >= 2):
        return "pattern", ref.split("::")[0], ref
    if kind == "finding" or (any_kind and ref in RULES):
        return "finding", None, ref
    whole = find_model(er, ref)
    if kind in (None, "model") and not model and whole is not None:
        return "model", whole.name, whole.name
    scoped = find_model(er, model)
    ms = [scoped] if scoped is not None else list(er.models)
    low = ref.lower()
    for m in ms:
        if kind in (None, "line_item") and "." in ref:
            for (mod, li) in m.model.line_items:
                if f"{mod}.{li}".lower() == low:
                    return "line_item", m.name, f"{mod}.{li}"
        if kind in (None, "module"):
            for mod in m.model.modules:
                if mod.lower() == low:
                    return "module", m.name, mod
        if kind in (None, "action"):
            for a in m.actions.actions:
                if a.lower() == low:
                    return "action", m.name, a
            for p in m.actions.processes:
                if p.lower() == low:
                    return "action", m.name, p
    if kind in (None, "line_item"):
        for m in ms:
            hits = [li for n, v in m.model.line_item_names().items() if n.lower() == low for li in v]
            if len(hits) == 1:
                return "line_item", m.name, f"{hits[0].module}.{hits[0].name}"
    if kind in (None, "model") and scoped is not None and low == scoped.name.lower():
        return "model", scoped.name, scoped.name
    return None, None, ref


def resolve(er, kind: str, model: str | None, ref: str, snapshot_id: str, status_of=None, edge_state_of=None) -> dict | None:
    """The object as a dict, or None when the snapshot does not contain it. Every related object carries an id."""
    ev = Evidence("", snapshot_id)

    def cite(k: str, mdl: str, r: str) -> str:
        return ev.mint(k, mdl, r).id

    if kind == "finding":
        return _rule(er, ref, cite, status_of)
    if kind == "pattern":
        return _pattern(er, ref, cite, status_of)
    m = find_model(er, model) or (find_model(er, ref) if kind == "model" else None)
    if kind == "model":
        return _model(er, m, cite, edge_state_of) if m is not None else None
    fn = {"module": lambda mm: _module(mm, ref, cite), "line_item": lambda mm: _line_item(mm, ref, cite, status_of), "action": lambda mm: _action(mm, ref, cite)}.get(kind)
    if fn is None:
        return None
    for mm in ([m] if m is not None else list(er.models)):      # no model named: the first model that holds the object answers
        out = fn(mm)
        if out is not None:
            return out
    return None


def _model(er, m, cite, edge_state_of) -> dict:
    f = m.facts or {}
    a = f.get("actions") or {}
    return {"kind": "model", "model": m.name, "ref": m.name, "name": m.name, "id": cite("model", m.name, m.name),
            "facts": {k: f.get(k) for k in ("modules", "line_items", "calculated", "cells", "parse_rate", "patterns", "findings", "edges", "unreferenced",
                                             "cycles", "has_effort", "effort_top10_share", "notes_coverage")},
            "dimensions": len(f.get("dimensions") or []),
            "referenced_by_agreement": (f.get("referenced_by_check") or {}).get("agreement"),
            "actions": {k: a.get(k) for k in ("imports", "exports", "processes", "latest_run", "stale_count", "orphan_count")} if a else None,
            "largest_modules": [{"ref": n, "id": cite("module", m.name, n), "cells": c, "pct": p} for n, c, p in (f.get("cells_by_module") or [])[:10]],
            "hubs": [{"ref": n, "id": cite("line_item", m.name, n), "dependents": c} for n, c in (f.get("hubs") or [])[:8]],
            "feeds": [{"model": e["to"], "id": cite("model", e["to"], e["to"]), "actions": e.get("actions"), "targets": list(e.get("targets") or [])[:5],
                       "state": edge_state_of(m.name, e["to"]) if edge_state_of else None}
                      for e in er.edges if e["from"] == m.name],
            "fed_by": [{"model": e["from"], "id": cite("model", e["from"], e["from"]), "actions": e.get("actions"),
                        "state": edge_state_of(e["from"], m.name) if edge_state_of else None} for e in er.edges if e["to"] == m.name],
            "warnings": list(m.model.warnings)[:10], "missing_columns": list(m.model.missing_columns)}


def _module(m, ref: str, cite) -> dict | None:
    mod = m.model.modules.get(ref) or next((v for k, v in m.model.modules.items() if k.lower() == ref.lower()), None)
    if mod is None:
        return None
    lis = m.model.by_module(mod.name)
    me = m.graph.module_edges()
    return {"kind": "module", "model": m.name, "ref": mod.name, "name": mod.name, "id": cite("module", m.name, mod.name),
            "functional_area": mod.functional_area, "applies_to": list(mod.applies_to), "dims_inferred": mod.dims_inferred,
            "time_scale": mod.time_scale, "versions": mod.versions, "cells": mod.cell_count or sum(x.cell_count for x in lis), "notes": mod.notes,
            "line_item_count": len(lis),
            "line_items": [{"ref": f"{mod.name}.{x.name}", "name": x.name, "id": cite("line_item", m.name, f"{mod.name}.{x.name}"), "formula": x.formula[:160],
                            "cells": x.cell_count, "format": x.format_type, "is_header": x.is_header} for x in lis[:_MAX_ITEMS]],
            "truncated": len(lis) > _MAX_ITEMS,
            "uses_modules": [{"ref": x, "id": cite("module", m.name, x)} for x in sorted(me.get(mod.name, ()))],
            "used_by_modules": [{"ref": a, "id": cite("module", m.name, a)} for a in sorted(a for a, bs in me.items() if mod.name in bs)],
            "imports": [{"ref": a.name, "id": cite("action", m.name, a.name), "last_run": a.last_run} for a in m.actions.actions.values() if a.target == mod.name][:20]}


def _decision(status_of, key: str) -> dict:
    """status and, when the owner recorded one, the decision (reason, who, when). status_of may return the bare status
    (the CLI workspace) or the whole record (the store)."""
    if status_of is None:
        return {"status": "open", "decision": None}
    r = status_of(key)
    if isinstance(r, dict):
        st = r.get("status") or "open"
        return {"status": st, "decision": ({"status": st, "reason": r.get("reason") or "", "by": r.get("by"), "when": r.get("when")} if st != "open" or r.get("reason") else None)}
    return {"status": r or "open", "decision": None}


def _line_item(m, ref: str, cite, status_of=None) -> dict | None:
    from ..store import pattern_id
    key = next((k for k in m.model.line_items if f"{k[0]}.{k[1]}" == ref), None) \
        or next((k for k in m.model.line_items if f"{k[0]}.{k[1]}".lower() == ref.lower()), None)
    if key is None:
        return None
    li = m.model.line_items[key]
    g = m.graph
    canon = f"{key[0]}.{key[1]}"
    uses = sorted(g.edges.get(key, ()))
    used_by = sorted(g.rev.get(key, ()))
    findings = [f for f in m.lint.findings if f.module == key[0] and (f.line_item or "") == key[1]]
    pats = []
    for c in m.clusters:
        if any(f.module == key[0] and f.line_item == key[1] for f in c.findings):
            pid = pattern_id(m, c)
            pats.append({"id": pid, "cite": cite("pattern", m.name, pid), "rule": c.rule, "severity": c.severity, "label": c.label, "count": c.count,
                         **_decision(status_of, pid)})

    def t(k):
        return f"{k[0]}.{k[1]}"

    return {"kind": "line_item", "model": m.name, "ref": canon, "name": key[1], "module": key[0], "id": cite("line_item", m.name, canon),
            "module_id": cite("module", m.name, key[0]),
            "formula": li.formula, "format": li.format_type, "applies_to": list(li.applies_to), "time_scale": li.time_scale, "time_range": li.time_range,
            "versions": li.versions, "summary": li.summary, "cells": li.cell_count, "calc_effort": li.calc_effort, "has_effort": bool((m.facts or {}).get("has_effort")),
            "notes": li.notes, "referenced_by": li.referenced_by_raw, "is_header": li.is_header, "parse_error": g.parse_errors.get(key),
            "references": [{"path": ".".join(r.path), "kind": r.kind, "target": t(r.target) if r.target else None,
                            "id": cite("line_item", m.name, t(r.target)) if r.target else None} for r in g.refs.get(key, [])][:80],
            "uses": [{"ref": t(k), "id": cite("line_item", m.name, t(k))} for k in uses[:80]], "uses_count": len(uses),
            "used_by": [{"ref": t(k), "id": cite("line_item", m.name, t(k))} for k in used_by[:80]], "used_by_count": len(used_by),
            "findings": [{"rule": f.rule, "rule_id": cite("finding", "", f.rule), "severity": f.severity, "message": f.message, "fix": f.fix, "source": f.source}
                         for f in findings][:20],
            "patterns": pats}


def _action(m, ref: str, cite) -> dict | None:
    a = m.actions.actions.get(ref) or next((v for k, v in m.actions.actions.items() if k.lower() == ref.lower()), None)
    if a is not None:
        return {"kind": "action", "model": m.name, "ref": a.name, "name": a.name, "id": cite("action", m.name, a.name), "action_kind": a.kind,
                "target": a.target, "target_id": cite("module", m.name, a.target) if a.target and a.target in m.model.modules else None,
                "detail": a.detail, "last_run": a.last_run, "duration_ms": a.duration_ms,
                "processes": [{"ref": p, "id": cite("action", m.name, p)} for p in a.processes], "notes": a.notes}
    p = m.actions.processes.get(ref) or next((v for k, v in m.actions.processes.items() if k.lower() == ref.lower()), None)
    if p is not None:
        return {"kind": "action", "model": m.name, "ref": p.name, "name": p.name, "id": cite("action", m.name, p.name), "action_kind": "process",
                "last_run": p.last_run, "duration_ms": p.duration_ms, "steps": [{"ref": s, "id": cite("action", m.name, s)} for s in p.steps]}
    return None


def _tests_of(rule: str) -> list[dict]:
    """The tests of the catalogue a rule belongs to, by number and title."""
    from . import checks as checksmod
    return checksmod.for_rule(rule)


def _pattern(er, ref: str, cite, status_of=None) -> dict | None:
    from anaplan_estate.lint import RULES
    parts = ref.split("::")
    if len(parts) < 3:
        return None
    mname, rule, label = parts[0], parts[1], "::".join(parts[2:])
    m = find_model(er, mname)
    if m is None:
        return None
    for c in m.clusters:
        if c.rule == rule and c.label == label:
            r = RULES.get(rule)
            keys = {f"{k[0]}.{k[1]}" for k in m.model.line_items}
            return {"kind": "pattern", "model": m.name, "ref": ref, "name": ref, "id": cite("pattern", m.name, ref), "rule": rule, "rule_id": cite("finding", "", rule),
                    "title": r.title if r else rule, "severity": c.severity, "key": c.key, "label": c.label, "count": c.count,
                    "modules": [{"ref": x, "id": cite("module", m.name, x)} for x in c.modules[:20]],
                    "objects": [{"ref": o, "id": cite("line_item", m.name, o) if o in keys else (cite("module", m.name, o) if o in m.model.modules else None)}
                                for o in c.objects[:12]],
                    "message": c.message, "fix": c.fix, **_decision(status_of, ref), "planual": list(r.planual) if r else [], "tests": _tests_of(rule)}
    return None


def _rule(er, ref: str, cite, status_of=None) -> dict | None:
    from anaplan_estate.lint import RULES
    from ..store import pattern_id
    r = RULES.get(ref)
    if not r:
        return None
    pats = []
    for m in er.models:
        for c in m.clusters:
            if c.rule == r.id:
                pid = pattern_id(m, c)
                pats.append({"id": pid, "cite": cite("pattern", m.name, pid), "model": m.name, "label": c.label, "count": c.count, "severity": c.severity,
                             **_decision(status_of, pid)})
    return {"kind": "finding", "model": "", "ref": r.id, "name": r.id, "id": cite("finding", "", r.id), "title": r.title, "severity": r.severity, "source": r.source,
            "description": r.description, "thresholds": dict(r.thresholds or {}), "planual": list(r.planual), "docs": list(r.docs),
            "tests": _tests_of(r.id), "in_estate": {m.name: (m.lint.counts.get("by_rule") or {}).get(r.id, 0) for m in er.models}, "patterns": pats[:30]}


# ---------- the export row ----------
_ROWS: dict[str, tuple[list[str], dict]] = {}
_ROWS_MAX = 6


def _index(path: Path, kind: str) -> tuple[list[str], dict]:
    """The export parsed once: header row plus an index from the object's key to its row, exactly as exported."""
    from anaplan_estate.model import open_csv
    rows, fields, _, _ = open_csv(path)
    index: dict = {}
    first = fields[0] if fields else ""
    if kind == "line_items":
        has_fmt, has_mod = "Format" in fields, "Module Name" in fields
        current = None
        for row in rows:
            name = row.get(first, "") or ""
            mod_col = row.get("Module Name", "") or ""
            formula = (row.get("Formula") or "").strip()
            fmt = row.get("Format", "") or ""
            if has_fmt:
                hdr = not fmt and not formula and not mod_col
            elif has_mod:
                hdr = not mod_col and not formula
            else:
                hdr = not formula and not (row.get("Applies To") or row.get("Cell Count") or row.get("Time Scale"))
            if hdr:
                current = name
                index.setdefault(("", name.lower()), row)          # the module's own header row
                continue
            index.setdefault(((mod_col or current or "").lower(), name.lower()), row)
    else:
        for row in rows:
            name = row.get(first, "") or ""
            if name:
                index.setdefault(name.lower(), row)
    return fields, index


def export_row(snaps, snapshot_id: str, model_name: str, kind: str, key) -> dict | None:
    """The row of the snapshot's export for one object: line item key (module, name), or a module or action name.
    None when the snapshot has no such file; a dict with row None when the file has no such row."""
    f = next((x for x in snaps.files(snapshot_id) if x["model"] == model_name and x["kind"] == kind), None)
    if not f:
        return None
    sha = f["blob_sha"]
    hit = _ROWS.get(sha)
    if hit is None:
        hit = _index(snaps.blobs.path(sha), kind)
        _ROWS[sha] = hit
        while len(_ROWS) > _ROWS_MAX:
            _ROWS.pop(next(iter(_ROWS)))
    fields, index = hit
    if kind == "line_items":
        k = (str(key[0]).lower(), str(key[1]).lower()) if isinstance(key, (tuple, list)) else ("", str(key).lower())
    else:
        k = str(key).lower()
    row = index.get(k)
    return {"file": f["original_name"], "uploaded_at": f["uploaded_at"], "kind": kind, "columns": list(fields),
            "row": {c: (row.get(c) or "") for c in fields} if row is not None else None}
