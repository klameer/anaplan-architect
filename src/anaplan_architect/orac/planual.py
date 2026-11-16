"""Planual flags: advisory, never a gate.

The estate engine's checks each rest on Planual rule numbers where there is one (18 numbers across 24 checks; the rest
are the tool's own tests). Here those checks are run over work that is only planned: the plan's new line items and
changed formulas are merged into a copy of the model, the checks that can be judged from an export are run over the
copy, and each planned item is marked "As per Planual 2.02-01" or "Departs from Planual 2.03-01" with one line of why,
in this model's own terms.

A departure never rejects a plan: the owner may have a reason, and the validator is the gate for correctness, not this.
Only rule numbers and the tool's own wording appear. The Planual's text is never shown.
"""
from __future__ import annotations
import copy, re
from anaplan_estate import lint as elint
from anaplan_grammar.model import LineItem, Module
from anaplan_grammar.parser import parse

# the checks that can say something about a line item that does not exist yet: they read the formula, the format or the
# summary method, not cell counts or usage
NEW_WORK = ("A-IF-COUNT", "F-LONG", "F-HARDCODE", "F-MIXED-CLAUSE", "F-SELECT-TIME", "A-DAISY", "A-SYSTEMS-FN", "A-SUMMARY-ON", "A-TEXT-FORMAT",
            "A-LI-COUNT", "F-DIVIDE-FN")
OVERRIDES = {"A-SUMMARY-ON": {"min_cells": -1}, "A-TEXT-FORMAT": {"min_cells": -1}}       # a planned line item has no cell count yet
_FORMAT = {"number": "NUMBER", "boolean": "BOOLEAN", "text": "TEXT", "date": "DATE", "list": "LIST", "time period": "TIME_ENTITY", "no data": "NONE"}
OWN = {"A-TEXT-FORMAT": "a text line item: it cannot be summed and it is heavier than a list-formatted one",
       "A-SUMMARY-ON": "its summary method is on and no formula reads its totals"}


def numbers(rule_id: str) -> list[str]:
    r = elint.RULES.get(rule_id)
    return list(r.planual) if r else []


def label(rule_id: str, state: str = "departs") -> str:
    """'As per Planual 2.02-01, 2.02-02', 'Departs from Planual 2.03-01', or the same of the tool's own test."""
    ns = numbers(rule_id)
    what = ("Planual " + ", ".join(ns)) if ns else "the tool's own test"
    return ("As per " if state == "as_per" else "Departs from ") + what


def catalogue() -> dict:
    """What can be flagged at all: how many Planual rule numbers the checks rest on, across how many checks."""
    nums = {n for r in elint.RULES.values() for n in r.planual}
    return {"numbers": len(nums), "checks": len(elint.RULES), "with_number": sum(1 for r in elint.RULES.values() if r.planual),
            "line": f"It flags the Planual rules it can see in an export: {len(nums)} rule numbers across {len(elint.RULES)} checks. It does not check the Planual."}


def merged(model, plan: dict):
    """A copy of the model with the plan's new modules and line items in it and its changed formulas applied. The model
    itself is not touched."""
    m = copy.copy(model)
    m.line_items = dict(model.line_items)
    m.modules = dict(model.modules)
    m.dimensions = set(model.dimensions)
    for mod in plan.get("modules") or []:
        name = mod["name"]
        old = m.modules.get(name)
        dims = tuple(mod.get("applies_to") or (old.applies_to if old else ()))
        nm = copy.copy(old) if old else Module(name=name, applies_to=dims)
        nm.line_items = list(old.line_items) if old else []
        for it in mod.get("items") or []:
            li = LineItem(module=name, name=it["name"], formula=it.get("formula") or "", format_type=_FORMAT.get(str(it.get("format") or "").lower(), "NUMBER"),
                          applies_to=tuple(it.get("applies_to") or dims), summary=str(it.get("summary") or "None").upper(), cell_count=0)
            m.line_items[li.key] = li
            nm.line_items.append(it["name"])
        m.modules[name] = nm
        m.dimensions |= set(dims)
    for c in plan.get("changes") or []:
        k = (c["module"], c["name"])
        if k in m.line_items:
            li = copy.copy(m.line_items[k]); li.formula = c["formula"]
            m.line_items[k] = li
    return m


def _ifs(formula: str) -> int:
    try:
        tree = parse(formula)
    except Exception:
        return 0
    n = 0
    stack = [tree]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            n += x.get("t") == "if"
            stack.extend(x.values())
        elif isinstance(x, (list, tuple)):
            stack.extend(x)
    return n


def _as_per(li, flagged: set[str]) -> list[tuple[str, str]]:
    """What a planned line item does that a rule asks for, said only where the item exercises the rule."""
    out = []
    f = li.formula or ""
    n = _ifs(f) if f else 0
    if n and "A-IF-COUNT" not in flagged:
        out.append(("A-IF-COUNT", f"{n} IF{'s' if n != 1 else ''}: the tool flags more than {elint.RULES['A-IF-COUNT'].thresholds.get('max_ifs', 10)}"))
    if li.format_type == "NUMBER" and "A-SUMMARY-ON" not in flagged and li.summary.split(";")[0] in ("NONE", "", "-"):
        out.append(("A-SUMMARY-ON", "summary off: no totals are calculated that nothing reads"))
    if f and re.search(r"\b(SUM|LOOKUP|SELECT)\b", f.upper()) and "F-MIXED-CLAUSE" not in flagged:
        out.append(("F-MIXED-CLAUSE", "one kind of lookup in the formula, not SUM mixed with LOOKUP or SELECT"))
    if f and "F-HARDCODE" not in flagged and re.search(r"[A-Za-z]", f) and not re.fullmatch(r"\s*(TRUE|FALSE)\s*", f.upper()):
        out.append(("F-HARDCODE", "no hard-coded figure: what it uses is read from line items"))
    return out[:2]


def flags(model_run, plan: dict) -> list[dict]:
    """Every flag on the plan's new line items and changed formulas: departures first (each with why, in the check's own
    measured terms), then what an item does as a rule asks. Advisory: nothing here rejects anything."""
    m = merged(model_run.model, plan)
    planned = {(mod["name"], it["name"]): "new" for mod in plan.get("modules") or [] for it in mod.get("items") or []}
    planned |= {(c["module"], c["name"]): "changed" for c in plan.get("changes") or []}
    grown = {mod["name"] for mod in plan.get("modules") or []}
    try:
        res = elint.lint(m, rules=list(NEW_WORK), overrides=OVERRIDES)
        found = res.findings
    except Exception:
        found = []
    out: list[dict] = []
    by_item: dict[tuple, set[str]] = {}
    for f in found:
        key = (f.module, f.line_item)
        if f.line_item and key in planned:
            by_item.setdefault(key, set()).add(f.rule)
            out.append({"object": f"{f.module}.{f.line_item}", "module": f.module, "name": f.line_item, "on": planned[key], "rule": f.rule, "planual": numbers(f.rule),
                        "state": "departs", "label": label(f.rule, "departs"), "why": OWN.get(f.rule) or f.message})
        elif not f.line_item and f.module in grown and f.rule == "A-LI-COUNT":
            out.append({"object": f.module, "module": f.module, "name": None, "on": "module", "rule": f.rule, "planual": numbers(f.rule), "state": "departs",
                        "label": label(f.rule, "departs"), "why": f.message})
    for key in planned:
        li = m.line_items.get(key)
        if li is None:
            continue
        for rule, why in _as_per(li, by_item.get(key, set())):
            out.append({"object": f"{key[0]}.{key[1]}", "module": key[0], "name": key[1], "on": planned[key], "rule": rule, "planual": numbers(rule), "state": "as_per",
                        "label": label(rule, "as_per"), "why": why})
    order = {"departs": 0, "as_per": 1}
    out.sort(key=lambda x: (order[x["state"]], x["object"], x["rule"]))
    return out


def attach(model_run, plan: dict) -> dict:
    """Put the flags on the plan: all of them under plan['planual'], and each on the line item or change it concerns."""
    fl = flags(model_run, plan)
    by: dict[str, list] = {}
    for f in fl:
        by.setdefault(f["object"], []).append({k: f[k] for k in ("rule", "planual", "state", "label", "why")})
    for mod in plan.get("modules") or []:
        for it in mod.get("items") or []:
            it["flags"] = by.get(f"{mod['name']}.{it['name']}", [])
    for c in plan.get("changes") or []:
        c["flags"] = by.get(f"{c['module']}.{c['name']}", [])
    cat = catalogue()
    plan["planual"] = {"flags": fl, "departs": sum(1 for f in fl if f["state"] == "departs"), "as_per": sum(1 for f in fl if f["state"] == "as_per"),
                       "note": "Flags only. A departure does not reject a plan: you may have a reason. " + cat["line"]}
    return plan


# ---------- on a finding: the rule numbers it rests on, and whether the owner has already decided ----------
KEPT = re.compile(r"on purpose|deliberate|deferred|accepted as the cost|kept until|is to be kept|stays (?:available|in the)|not to be (?:changed|deleted|removed|built on)|"
                  r"nothing is to be built|agreed in principle|do not (?:touch|change|delete|remove)", re.I)


def card_rules(er, finding_ids: list[str]) -> tuple[list[str], str]:
    """The Planual rule numbers the findings of a card rest on, and how the card says it: the numbers, or that it is the
    tool's own test."""
    fmap = {f.id: f for f in er.findings}
    nums = sorted({n for fid in finding_ids or [] if fid in fmap for r in fmap[fid].rules for n in numbers(r)})
    return nums, ("Planual " + ", ".join(nums)) if nums else "the tool's own test"


def kept(db, eid: str, model: str, objects: list[str], state: dict | None = None, snapshot_id: str | None = None) -> dict | None:
    """A deliberate exception the owner has recorded for one of these objects, if there is one: a decision or constraint
    note on the object or its module, else a document section that names it and says it is kept or deferred, else the
    card's own state. Returned with what to open."""
    from .evidence import Evidence
    ev = Evidence(eid, snapshot_id or "")
    mods = {o.split(".", 1)[0] for o in objects or []}
    items = {tuple(o.split(".", 1)) for o in objects or [] if "." in o}
    if mods:
        rows = db.q("SELECT n.id, n.title, n.type, n.body, o.scope, o.module, o.line_item FROM notes n JOIN note_objects o ON o.note_id=n.id JOIN models m ON m.id=o.model_id "
                    "WHERE n.estate_id=? AND n.status!='superseded' AND n.type IN ('decision','constraint') AND o.scope IN ('module','line_item') AND m.name=? "
                    "ORDER BY (n.status='user_confirmed') DESC, n.updated DESC", eid, model)
        for r in rows:
            hit = (r["scope"] == "line_item" and (r["module"], r["line_item"]) in items) or (r["scope"] == "module" and r["module"] in mods)
            if hit and KEPT.search((r["title"] or "") + " " + (r["body"] or "")):
                return {"by": "note", "id": r["id"], "title": r["title"], "kind": "note", "citation": ev.mint("note", "", r["id"], r["title"], tool="notes").id}
        refs = sorted(set(objects or []) | mods)
        q = ("SELECT s.id, s.heading, s.text, d.title FROM doc_section_objects x JOIN doc_sections s ON s.id=x.section_id JOIN documents d ON d.id=s.document_id "
             f"WHERE d.estate_id=? AND x.model=? AND x.ref IN ({','.join('?' * len(refs))}) ORDER BY d.doc_date DESC, s.seq")
        for r in db.q(q, eid, model, *refs):
            if KEPT.search(r["text"] or ""):
                title = f"{r['title']} · {r['heading']}" if r["heading"] else r["title"]
                return {"by": "document", "id": r["id"], "title": title, "kind": "document", "citation": ev.mint("document", "", r["id"], title, "get_section").id}
    if state and state.get("state") == "keep_current_design":
        return {"by": "decision", "id": None, "title": state.get("reason") or "the owner chose to keep the current design", "kind": "decision", "citation": None}
    return None
