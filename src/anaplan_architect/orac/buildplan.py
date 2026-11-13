"""A build plan, checked by code (v0.2 P3). The model proposes modules, line items, formats, applies-to, summaries and
formulas; this parses every formula with anaplan-grammar, resolves every reference against the model as it is and
against the plan's own new objects, sorts the line items and the modules into build order (nothing before what it
refers to) and rejects a plan with a formula that does not parse, a reference that resolves to nothing, or a cycle.

A plan that passes is returned in the shape the page draws; one that does not is returned as the list of what to fix.
Nothing here builds anything in Anaplan: a plan is a proposal.
"""
from __future__ import annotations
import csv, io, re
from anaplan_grammar.parser import parse, ParseError, references_ctx
from anaplan_estate.graph import PSEUDO_LISTS, LIST_ARG
from anaplan_estate.model import LineItem

FORMATS = ("Number", "Boolean", "Text", "Date", "List", "Time period", "No data")
MAX_MODULES, MAX_ITEMS = 12, 120


def _refs(tree) -> list[tuple[tuple[str, ...], str | None, int | None]]:
    out = []
    try:
        for r in references_ctx(tree):
            if isinstance(r, tuple) and len(r) == 3:
                out.append((tuple(r[0]), r[1], r[2]))
            else:
                out.append((tuple(r), None, None))
    except Exception:
        from anaplan_grammar.parser import references
        out = [(tuple(p), None, None) for p in references(tree)]
    return out


def _toposort(nodes: list, deps: dict) -> tuple[list, list]:
    """Stable topological order (proposal order among equals). Returns (order, the nodes left in a cycle)."""
    done, order = set(), []
    remaining = list(nodes)
    while remaining:
        ready = [n for n in remaining if all(d in done or d not in deps for d in deps.get(n, ()) if d != n)]
        if not ready:
            return order, remaining
        for n in ready:
            order.append(n); done.add(n)
        remaining = [n for n in remaining if n not in done]
    return order, []


def _format(raw: str) -> str | None:
    """A line item format as Anaplan names it ("list: Segments" gives "List: Segments"); None when it is not one."""
    f = (raw or "Number").strip()
    for known in sorted(FORMATS, key=len, reverse=True):
        if f.lower() == known.lower() or f.lower().startswith(known.lower() + ":") or f.lower().startswith(known.lower() + " "):
            return known + f[len(known):]
    return None


def _named(text: str) -> list[str]:
    """Object names a free-text line of the plan puts in backticks."""
    return [t.strip() for t in re.findall(r"`([^`]+)`", text or "") if t.strip()]


def check(model_run, proposal: list[dict], title: str = "", changes: list[dict] | None = None, checks_after: list[str] | None = None, lists: list[dict] | None = None) -> dict:
    """Check a proposed plan against one model.
    `proposal`: the modules to add or extend: {name, applies_to: [..], note, line_items: [{name, format, summary, formula, note}]}.
    `changes`: existing line items whose formula is replaced so the model switches over to what was built:
               {module, line_item, formula, note}. `checks_after`: what the builder checks once it is done.
    `lists`: the lists or line item subsets the plan needs that the model does not have: {name, what}, where `what` says
             what it is and what it holds, in a line."""
    m = model_run.model
    g = model_run.graph
    errors: list[dict] = []
    changes = changes or []; checks_after = [str(c).strip() for c in (checks_after or []) if str(c).strip()]
    list_what = {str((x or {}).get("name") or "").strip(): str((x or {}).get("what") or "").strip() for x in (lists or []) if isinstance(x, dict) and str(x.get("name") or "").strip()}
    if not isinstance(proposal, list) or (not proposal and not changes):
        return {"ok": False, "rejected": [{"what": "plan", "why": "modules must be a non-empty list of {name, applies_to, line_items}"}]}
    if len(proposal) > MAX_MODULES or sum(len(p.get("line_items") or []) for p in proposal if isinstance(p, dict)) > MAX_ITEMS or len(changes) > MAX_ITEMS:
        return {"ok": False, "rejected": [{"what": "plan", "why": f"a plan holds at most {MAX_MODULES} modules and {MAX_ITEMS} line items: split it"}]}
    mods: dict[str, dict] = {}
    for p in proposal:
        name = str((p or {}).get("name") or "").strip()
        if not name:
            errors.append({"what": "module", "why": "a module has no name"}); continue
        if name in mods:
            errors.append({"what": name, "why": "the plan names this module twice"}); continue
        existing = m.modules.get(name) or next((v for k, v in m.modules.items() if k.lower() == name.lower()), None)
        if existing is not None:
            name = existing.name
        have = [li for li in (existing.line_items if existing else [])]
        dims = [str(d).strip() for d in (p.get("applies_to") or []) if str(d).strip()] or (list(existing.applies_to) if existing else [])
        items = []
        seen = set()
        for it in p.get("line_items") or []:
            n = str((it or {}).get("name") or "").strip()
            if not n:
                errors.append({"what": name, "why": "a line item has no name"}); continue
            if n.lower() in seen:
                errors.append({"what": f"{name}.{n}", "why": "the plan names this line item twice"}); continue
            seen.add(n.lower())
            if any(n.lower() == h.lower() for h in have):
                errors.append({"what": f"{name}.{n}", "why": "this line item already exists in the model: list it under changes, with its whole new formula, to change it"}); continue
            fmt = _format(str(it.get("format") or ""))
            if fmt is None:
                errors.append({"what": f"{name}.{n}", "why": f"{str(it.get('format'))[:40]!r} is not a line item format: use one of {', '.join(FORMATS)}"}); continue
            items.append({"name": n, "format": fmt, "summary": str(it.get("summary") or "None").strip(),
                          "formula": str(it.get("formula") or "").strip().lstrip("=").strip(), "note": str(it.get("note") or "").strip(),
                          "applies_to": [str(d).strip() for d in (it.get("applies_to") or []) if str(d).strip()]})
        if not items:
            errors.append({"what": name, "why": "the module has no new line items"})
        mods[name] = {"name": name, "state": "new" if existing is None else ("fill" if not have else "exists"), "applies_to": dims,
                      "note": str(p.get("note") or "").strip(), "items": items, "have": have}
    # the existing line items the plan switches over
    chg: list[dict] = []
    for c in changes:
        cm, cn = str((c or {}).get("module") or "").strip(), str((c or {}).get("line_item") or (c or {}).get("name") or "").strip()
        key = next((k for k in m.line_items if k[0].lower() == cm.lower() and k[1].lower() == cn.lower()), None)
        if key is None:
            errors.append({"what": f"{cm}.{cn}", "why": "a change names a line item the model does not have: only an existing line item can be changed; a new one goes in its module's line_items"}); continue
        if any(x["key"] == key for x in chg):
            errors.append({"what": f"{key[0]}.{key[1]}", "why": "the plan changes this line item twice"}); continue
        formula = str(c.get("formula") or "").strip().lstrip("=").strip()
        old = (m.line_items[key].formula or "").strip().lstrip("=").strip()
        if not formula:
            errors.append({"what": f"{key[0]}.{key[1]}", "why": "a change needs the whole new formula"}); continue
        if formula == old:
            errors.append({"what": f"{key[0]}.{key[1]}", "why": "the new formula is the formula the line item already has: nothing changes"}); continue
        chg.append({"key": key, "module": key[0], "name": key[1], "formula": formula, "old_formula": old, "note": str(c.get("note") or "").strip()})
    if errors:
        return {"ok": False, "rejected": errors}

    planned = {(mn, it["name"]) for mn, mod in mods.items() for it in mod["items"]}
    plan_dims = {d for mod in mods.values() for d in mod["applies_to"]} | {d for mod in mods.values() for it in mod["items"] for d in it["applies_to"]} | set(list_what)
    known_dims = set(m.dimensions) | plan_dims
    new_dims = sorted(d for d in plan_dims if d not in m.dimensions and d.upper() not in PSEUDO_LISTS and d.lower() != "time")
    item_deps: dict = {}
    reads: dict[str, set] = {mn: set() for mn in mods}                 # module -> modules it reads (existing or planned)
    count = {"formulas": 0, "parsed": 0, "existing": 0, "new": 0}
    used_items: dict = {}                                               # existing line items the build refers to, in first-use order
    used_lists: dict = {}
    old_reads: dict = {}                                                # new line item -> the existing line items its formula reads

    def resolve(mn: str, name: str, formula: str) -> tuple[list[dict], set, set]:
        """The references of one formula, each resolved against the model and the plan; faults go to `errors`.
        Returns the references, the new line items it reads and the existing line items it reads."""
        refs, deps, olds = [], set(), set()
        count["formulas"] += 1
        try:
            tree = parse(formula)
        except (ParseError, ValueError, IndexError, KeyError, RecursionError) as e:      # what the grammar raises on text that is not a formula
            errors.append({"what": f"{mn}.{name}", "why": f"the formula does not parse: {str(e)[:160]}", "formula": formula}); return refs, deps, olds
        count["parsed"] += 1
        probe = LineItem(module=mn, name=name, formula=formula)
        for path, fn, argi in _refs(tree):
            fn = fn.upper() if isinstance(fn, str) else fn
            kind, target, is_new = "unresolved", None, False
            if len(path) == 1:
                n = path[0]
                if (fn, argi) in LIST_ARG:
                    kind = "dimension" if (n in known_dims or n.upper() in PSEUDO_LISTS) else "unresolved"
                elif (mn, n) in planned:
                    kind, target, is_new = "line_item", (mn, n), True
                elif (mn, n) in m.line_items:
                    kind, target = "line_item", (mn, n)
                elif n in known_dims or n.upper() in PSEUDO_LISTS or n in m.modules or n in mods:
                    kind = "dimension"
            else:
                a, b = path[0], path[1]
                mod_name = a if a in mods else next((k for k in m.modules if k.lower() == a.lower()), a)
                if (mod_name, b) in planned:
                    kind, target, is_new = "line_item", (mod_name, b), True
                elif (mod_name, b) in m.line_items:
                    kind, target = "line_item", (mod_name, b)
                elif a in known_dims or a.upper() in PSEUDO_LISTS:
                    kind = "list_item"                              # a member on a list: the exports hold no members, so it is not checked
                elif mod_name in mods or mod_name in m.modules:
                    kind = "unresolved"                             # a real module, but no such line item in it
                else:
                    r = g.resolve(probe, list(path), fn, argi)
                    kind = "unresolved" if r.kind in ("unresolved", "list_item") else r.kind
            if kind == "unresolved":
                hint = ("no such line item in that module" if len(path) > 1 and (path[0] in mods or path[0] in m.modules)
                        else "neither a module of the model, a module of this plan, nor a list the model or the plan applies to")
                errors.append({"what": f"{mn}.{name}", "why": f"the reference {'.'.join(path)} resolves to nothing: {hint}", "formula": formula})
                continue
            refs.append({"path": ".".join(path), "kind": kind, "module": target[0] if target else None, "new": is_new})
            if kind in ("dimension", "list_item") and path[0] in m.dimensions:
                used_lists.setdefault(path[0], True)
            if target:
                if is_new:
                    count["new"] += 1
                    if target != (mn, name):
                        deps.add(target)
                else:
                    count["existing"] += 1
                    olds.add(target)
                    if target != (mn, name):
                        used_items.setdefault(target, True)
        return refs, deps, olds

    for mn, mod in mods.items():
        for d in mod["applies_to"]:
            if d in m.dimensions:
                used_lists.setdefault(d, True)
        for it in mod["items"]:
            key = (mn, it["name"]); item_deps[key] = set(); it["refs"] = []; old_reads[key] = set()
            if not it["formula"]:
                continue
            it["refs"], item_deps[key], old_reads[key] = resolve(mn, it["name"], it["formula"])
            for r in it["refs"]:
                if r["module"] and r["module"] != mn:
                    reads[mn].add(r["module"])
    for c in chg:
        c["refs"], c["deps"], c["olds"] = resolve(c["module"], c["name"], c["formula"])
    if errors:
        return {"ok": False, "rejected": errors}

    # build order: line items first (a cycle among new line items is a fault), then modules
    order, stuck = _toposort(list(item_deps), item_deps)
    if stuck:
        return {"ok": False, "rejected": [{"what": ", ".join(f"{a}.{b}" for a, b in stuck[:8]), "why": "these new line items refer to each other in a cycle: nothing can be built first"}]}
    rank = {k: i for i, k in enumerate(order)}
    mod_deps = {mn: {d for d in reads[mn] if d in mods} for mn in mods}
    morder, mstuck = _toposort(list(mods), mod_deps)
    interleaved = bool(mstuck)
    if interleaved:
        # Modules that read each other, with no line item waiting on itself: Anaplan builds that. No module can be finished
        # before the other, so the modules are created first and the line items then go in their own order across them.
        morder = sorted(mods, key=lambda mn: min(rank[(mn, it["name"])] for it in mods[mn]["items"]))
    # a change must not close a loop. What each line item reads once the plan is built: a new one, its formula's
    # references (new and existing); a changed one, its new formula's; any other existing one, what the model's own
    # graph says it reads today. Walk from what a changed formula reads: if the walk comes back to it, Anaplan would
    # refuse the formula as circular, whatever path the loop takes.
    changed = {c["key"]: c for c in chg}

    def reads_of(k) -> set:
        if k in changed:
            return set(changed[k]["deps"]) | set(changed[k]["olds"])
        if k in item_deps:
            return set(item_deps[k]) | set(old_reads.get(k, ()))
        return set(g.edges.get(k, ()))
    for c in chg:
        came, todo, loop = {}, [(t, c["key"]) for t in reads_of(c["key"])], None
        while todo:
            k, via = todo.pop()
            if k in came:
                continue
            came[k] = via
            if k == c["key"]:
                loop = k; break
            todo.extend((n, k) for n in reads_of(k))
        if loop is not None:
            path, k = [], came[c["key"]]
            while k != c["key"] and len(path) < 12:
                path.append(k); k = came[k]
            way = " reads ".join(f"{a}.{b}" for a, b in [c["key"]] + list(reversed(path)) + [c["key"]])
            errors.append({"what": f"{c['module']}.{c['name']}", "why": f"the changed formula would make a circular reference: {way}. Read what it needs from a line item that does not depend on it"})
    # a name in backticks in a note or a check must be something the model or the plan has
    def known(name: str) -> bool:
        n = name.replace("'", "").strip().lower()
        if n in {k.lower() for k in m.modules} or n in {k.lower() for k in mods} or n in {d.lower() for d in known_dims} or n == model_run.name.lower():
            return True
        both = {f"{a}.{b}".lower() for a, b in m.line_items} | {f"{a}.{b}".lower() for a, b in planned}
        return n in both or n in {b.lower() for _a, b in planned} or n in {b.lower() for _a, b in m.line_items}
    for where, text in ([("a check", t) for t in checks_after] + [(f"the note on {mn}", mod["note"]) for mn, mod in mods.items()] + [(f"the list {n}", w) for n, w in list_what.items()] +
                        [(f"the note on {c['module']}.{c['name']}", c["note"]) for c in chg]):
        for name in _named(text):
            if not known(name):
                errors.append({"what": where, "why": f"it names `{name}`, which neither the model nor this plan has: use the exact name, or leave the backticks off words that are not object names"})
    if errors:
        return {"ok": False, "rejected": errors}

    existing = sorted({d for mn in mods for d in reads[mn] if d not in mods})
    out_mods = []
    for step, mn in enumerate(morder, 1):
        mod = mods[mn]
        items = sorted(mod["items"], key=lambda it: rank[(mn, it["name"])])
        out_mods.append({"step": step, "name": mn, "state": mod["state"], "applies_to": mod["applies_to"], "note": mod["note"], "reads": sorted(reads[mn]),
                         "items": [{"name": it["name"], "format": it["format"], "summary": it["summary"], "formula": it["formula"], "refs": it["refs"], "note": it["note"], "rank": rank[(mn, it["name"])],
                                    **({"applies_to": it["applies_to"]} if it["applies_to"] else {})} for it in items]})
    out_changes = [{"module": c["module"], "name": c["name"], "old_formula": c["old_formula"], "formula": c["formula"], "refs": c["refs"], "note": c["note"]} for c in chg]
    notes = ["Cell counts of the new modules: the exports do not say how large a list is until the module exists."]
    if new_dims:
        notes.append("Lists the plan applies to that the model's exports do not name: " + ", ".join(new_dims) + ". Create them first, or check the names.")
    if not checks_after and out_changes:
        checks_after = ["Compare " + ", ".join(f"`{c['module']}.{c['name']}`" for c in out_changes) + " before and after the change, on the same selection: the values should be the same unless the plan meant them to move."]
    uses = {"modules": sorted({k[0] for k in used_items} | set(existing) | {c["module"] for c in out_changes}),
            "line_items": [{"module": a, "name": b} for a, b in list(dict.fromkeys([(c["module"], c["name"]) for c in out_changes] + list(used_items)))], "lists": list(used_lists)}
    plan = {"model": model_run.name, "title": title.strip()[:160], "modules": out_mods, "existing": existing, "changes": out_changes, "after": checks_after[:12],
            "uses": uses, "new_lists": new_dims, "interleaved": interleaved, "list_notes": {d: list_what[d] for d in new_dims if list_what.get(d)},
            "edges": [[d, mn] for mn in morder for d in sorted(reads[mn])],
            "checks": {"formulas": count["formulas"], "parsed": count["parsed"], "refs_existing": count["existing"], "refs_new": count["new"], "ordered": True, "steps": len(out_mods),
                       "changes": len(out_changes), "notes": notes}}
    plan["steps"] = steps(plan)
    return {"ok": True, "plan": plan}


_STATE = {"new": "new module", "fill": "existing module, empty today", "exists": "existing module, extended"}


def steps(plan: dict) -> list[dict]:
    """The plan as numbered instructions a builder follows in Anaplan, in order: lists, then each module and its line
    items, then the existing formulas switched over, then what to check. Written by code from the checked plan."""
    out: list[dict] = []
    def add(kind: str, text: str, **more):
        out.append({"n": len(out) + 1, "kind": kind, "text": text, **more})
    for d in plan.get("new_lists") or []:
        what = (plan.get("list_notes") or {}).get(d)
        add("list", f"Create {d}: {what.rstrip('.')}." if what else f"Create the list {d}, unless the model already has it under another name.", name=d)
    def module_step(m):
        dims = ", ".join(m["applies_to"]) or "no dimensions"
        if m["state"] == "new":
            add("module", f"Create the module {m['name']} with dimensions {dims}." if m["applies_to"] else f"Create the module {m['name']} with no dimensions.", module=m["name"], applies_to=m["applies_to"])
        else:
            add("open", f"Open the existing module {m['name']} (dimensions: {dims}). Leave the line items it has as they are.", module=m["name"], applies_to=m["applies_to"])
    # modules that read each other are all created first; their line items then go in one order across them
    inter = bool(plan.get("interleaved"))
    if inter:
        for m in plan["modules"]:
            module_step(m)
    pairs = sorted(((m, it) for m in plan["modules"] for it in m["items"]), key=lambda p: p[1].get("rank", 0)) if inter else [(m, it) for m in plan["modules"] for it in m["items"]]
    last = None
    for m, it in pairs:
        if not inter and m is not last:
            module_step(m)
        last = m
        if True:
            own = f", applies to {', '.join(it['applies_to'])}" if it.get("applies_to") else ""
            text = f"In {m['name']}, add the line item {it['name']}: format {it['format']}, summary {it['summary'] or 'None'}{own}."
            add("line_item", text + (" Enter its formula:" if it["formula"] else " No formula: it is an input."), module=m["name"], item=it["name"], format=it["format"],
                summary=it["summary"] or "None", formula=it["formula"], refs=it.get("refs") or [], **({"applies_to": it["applies_to"]} if it.get("applies_to") else {}))
    for c in plan.get("changes") or []:
        add("change", f"In {c['module']}, replace the formula of the existing line item {c['name']}. This is the switch-over: do it last.", module=c["module"], item=c["name"],
            old_formula=c["old_formula"], formula=c["formula"], refs=c.get("refs") or [], note=c.get("note") or "")
    for t in plan.get("after") or []:
        add("check", t)
    return out


def order_holds(plan: dict) -> bool:
    """The property the order promises: every reference of a step is to the model as it is, to an earlier step, or to
    an earlier line item of the same step."""
    if plan.get("interleaved"):                        # modules that read each other: the line items' own order is what holds
        rank = {(m["name"], it["name"]): it["rank"] for m in plan["modules"] for it in m["items"]}
        return all(rank[(r["module"], r["path"].split(".")[-1])] < it["rank"] for m in plan["modules"] for it in m["items"] for r in it.get("refs") or []
                   if r.get("new") and (r["module"], r["path"].split(".")[-1]) != (m["name"], it["name"]))
    step_of = {m["name"]: m["step"] for m in plan["modules"]}
    for m in plan["modules"]:
        seen = set()
        for it in m["items"]:
            for r in it.get("refs") or []:
                if not r.get("new"):
                    continue
                if r["module"] == m["name"]:
                    if r["path"].split(".")[-1] not in seen and r["path"].split(".")[-1] != it["name"]:
                        return False
                elif step_of.get(r["module"], 10 ** 6) >= m["step"]:
                    return False
            seen.add(it["name"])
    return True


def to_markdown(plan: dict) -> str:
    c = plan["checks"]
    tick = chr(96)
    code = lambda f: tick + f.replace("|", chr(92) + "|") + tick
    out = [f"# Build plan: {plan.get('title') or plan['model']}", "", f"Model: {plan['model']}.", "", "## What you will build", ""]
    for m in plan["modules"]:
        out.append(f"- **{m['name']}** ({_STATE[m['state']]}; dimensions: {', '.join(m['applies_to']) or 'none'}){': ' + m['note'] if m.get('note') else ''}")
    u = plan.get("uses") or {}
    if u.get("modules") or u.get("line_items") or u.get("lists"):
        out += ["", "## What already exists that this uses", ""]
        if u.get("modules"):
            out.append("- Modules: " + ", ".join(u["modules"]))
        if u.get("line_items"):
            out.append("- Line items: " + ", ".join(f"{x['module']}.{x['name']}" for x in u["line_items"]))
        if u.get("lists"):
            out.append("- Lists: " + ", ".join(u["lists"]))
    out += ["", "## Line items to build", ""]
    for m in plan["modules"]:
        out += [f"### {m['name']}", "", "| Line item | Format | Dimensions | Summary | Formula |", "|---|---|---|---|---|"]
        for it in m["items"]:
            out.append(f"| {it['name']} | {it['format']} | {', '.join(it.get('applies_to') or m['applies_to']) or 'none'} | {it['summary']} | {code(it['formula']) if it['formula'] else 'input'} |")
        out.append("")
    out += ["## Steps", ""]
    for s in plan.get("steps") or steps(plan):
        out.append(f"{s['n']}. {('Check: ' if s['kind'] == 'check' else '') + s['text']}")
        if s["kind"] == "change":
            out += [f"   - from: {code(s['old_formula']) if s['old_formula'] else 'no formula'}", f"   - to: {code(s['formula'])}"]
        elif s.get("formula"):
            out.append(f"   - {code(s['formula'])}")
    out += ["", f"Checked: {c['parsed']} of {c['formulas']} formulas are valid Anaplan syntax; every name they use exists in the model or is built by this plan; "
            "order checked: nothing is built before what it refers to.", "", "A plan is a proposal: nothing has been built in Anaplan.", ""]
    return "\n".join(out)


def to_csv(plan: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Step", "Module", "Module state", "Applies To", "Order in module", "Line item", "Format", "Summary", "Formula"])
    for m in plan["modules"]:
        for i, it in enumerate(m["items"], 1):
            w.writerow([m["step"], m["name"], m["state"], ", ".join(it.get("applies_to") or m["applies_to"]), i, it["name"], it["format"], it["summary"], it["formula"]])
    for c in plan.get("changes") or []:
        w.writerow([len(plan["modules"]) + 1, c["module"], "change existing formula", "", "", c["name"], "", "", c["formula"]])
    return buf.getvalue()
