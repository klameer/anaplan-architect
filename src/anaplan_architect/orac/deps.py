"""The dependency explorer (Orac stage 4): queries over the parsed estate in the
shapes the page needs.

Everything rests on anaplan-estate's Graph. `Graph._closure` is the counting
spec (breadth-first, cycle-safe, shortest distance, the selection excluded even
when a cycle returns to it, every node counted once) and is called, never
reimplemented: a line item's reach is `_closure` from it; a module's reach is
`_closure` from a sentinel whose neighbours are the module's line items, with
the module's own items left out. What this file adds is presentation: a
searchable index of line items and modules; the reach of a change as unique
line items, modules and models, with actions listed separately at module level
(an import or export touches a module; the exports say nothing about which line
items it fills) and other models listed separately as inferred (the feeds are
read off import action names and never expanded into line-item lineage); one
predecessor per reached node so a path back to the selection can be shown; and
a neighbourhood in a form a graph can grow from one click at a time. Every
object carries a citation id bound to the snapshot, so a click opens the
evidence drawer. Coverage gaps sit beside every count.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from .evidence import Evidence
from .objects import find_model

DIRECTIONS = ("downstream", "upstream")
_START = ("", "\x00start")        # the sentinel a module reach starts from


class _WithStart:
    """The graph's adjacency plus one node whose neighbours are a set, so `_closure` from it is a multi-source
    closure (distances one too many, corrected by the caller) without a second breadth-first search."""

    def __init__(self, base, items):
        self.base, self.items = base, items

    def get(self, n, default=()):
        return self.items if n == _START else self.base.get(n, default)


def _citer(snapshot_id: str | None):
    ev = Evidence("", snapshot_id or "")
    return lambda kind, model, ref: ev.mint(kind, model, ref).id


def _clean(ref: str) -> str:
    return (ref or "").strip().strip("`").strip("'")


def li_key(m, ref: str):
    """(module, name) for a 'Module.Line Item' spelling, exact first, then case-insensitive; None when absent."""
    r = _clean(ref); low = r.lower()
    for k in m.model.line_items:
        if f"{k[0]}.{k[1]}" == r:
            return k
    for k in m.model.line_items:
        if f"{k[0]}.{k[1]}".lower() == low:
            return k
    return None


def module_name(m, ref: str) -> str | None:
    r = _clean(ref); low = r.lower()
    if r in m.model.modules:
        return r
    return next((mod for mod in m.model.modules if mod.lower() == low), None)


def coverage_notes(m, unmatched: int = 0) -> list[str]:
    """What the counts cannot see, beside them on the page."""
    f = m.facts or {}
    rc = f.get("referenced_by_check") or {}
    out = []
    if rc.get("agreement") is None:
        out.append("No Referenced By column in the export: the graph could not be checked against Anaplan's own dependency list.")
    elif rc["agreement"] < 0.95:
        out.append(f"Dependency coverage {rc['agreement']:.0%} against Anaplan's Referenced By: readers may be missing.")
    if f.get("parse_errors"):
        out.append(f"{f['parse_errors']} formula{'s' if f['parse_errors'] != 1 else ''} did not parse; their references are absent from the graph.")
    if not f.get("actions"):
        out.append("No Actions export: imports and exports not assessed.")
    elif unmatched:
        out.append(f"{unmatched} import or export action{'s' if unmatched != 1 else ''} name{'' if unmatched != 1 else 's'} a target that is not a module of this model "
                   "(a list, or a module missing from the Line Items export), so they cannot be placed on the reach.")
    out.append("Saved views, pages, dashboards and line item subsets are not in the exports. Reach describes formula references; it does not prove a value will change.")
    return out


# ---------- search ----------

def _row(m, li, g, cite, where: str) -> dict:
    k = li.key
    ref = f"{k[0]}.{k[1]}"
    return {"kind": "line_item", "model": m.name, "ref": ref, "id": cite("line_item", m.name, ref), "module": k[0], "module_id": cite("module", m.name, k[0]),
            "name": k[1], "formula": li.formula[:140], "calculated": bool(li.formula), "cells": li.cell_count,
            "effort": li.calc_effort if (m.facts or {}).get("has_effort") else None,
            "uses": len(g.edges.get(k, ())), "used_by": len(g.rev.get(k, ())), "in": where}


def search(er, q: str, model: str | None = None, kind: str | None = None, limit: int = 50, snapshot_id: str | None = None) -> dict:
    """Line items and modules whose name, module or formula contains the text. Name matches first, then module, then
    formula; within each the most depended-on first. With nothing typed, each model's hubs are the starting points."""
    cite = _citer(snapshot_id)
    t = _clean(q).lower()
    scoped = find_model(er, model) if model else None
    models = [scoped] if scoped is not None else list(er.models)
    hits: list[dict] = []
    if not t:
        for m in models:
            for k, _n in m.graph.hubs(limit):
                li = m.model.line_items.get(k)
                if li is not None and not li.is_header:
                    hits.append(_row(m, li, m.graph, cite, "hub"))
        hits.sort(key=lambda r: (-r["used_by"], r["model"], r["ref"]))
        return {"q": q or "", "hits": hits[:limit], "total": len(hits), "truncated": len(hits) > limit}
    rank = {"name": 0, "module": 1, "formula": 2}
    cap = max(limit * 20, 2000)
    for m in models:
        g = m.graph
        if kind in (None, "", "module"):
            me = g.module_edges()
            for mod in m.model.modules:
                if t in mod.lower():
                    lis = [x for x in m.model.by_module(mod) if not x.is_header]
                    hits.append({"kind": "module", "model": m.name, "ref": mod, "id": cite("module", m.name, mod), "module": mod, "module_id": cite("module", m.name, mod),
                                 "name": mod, "formula": "", "calculated": False, "cells": m.model.modules[mod].cell_count or sum(x.cell_count for x in lis),
                                 "effort": None, "uses": len(me.get(mod, ())), "used_by": sum(1 for a, bs in me.items() if mod in bs), "in": "name", "line_items": len(lis)})
        if kind in (None, "", "line_item"):
            for k, li in m.model.line_items.items():
                if li.is_header:
                    continue
                where = "name" if t in li.name.lower() else "module" if t in k[0].lower() else "formula" if t in li.formula.lower() else None
                if where:
                    hits.append(_row(m, li, g, cite, where))
                    if len(hits) >= cap:
                        break
    hits.sort(key=lambda r: (rank.get(r["in"], 3), 0 if r["kind"] == "module" else 1, -r["used_by"], r["model"], r["ref"]))
    return {"q": q, "hits": hits[:limit], "total": len(hits), "truncated": len(hits) > limit}


# ---------- reach ----------

def reach(er, model: str, ref: str, direction: str = "downstream", depth: int | None = None, snapshot_id: str | None = None, limit: int = 400) -> dict:
    """The reach of a change to one line item or one module: what depends on it (downstream) or what it depends on
    (upstream), counted as the spec counts (unique line items, shortest distance, the selection excluded), rolled up
    to unique modules, with the actions that touch a module in reach listed at module level and the other models the
    feeds name listed as inferred. `depth` caps the hops; None follows every link."""
    m = find_model(er, model)
    if m is None:
        return {"error": f"no model named {model!r}"}
    if direction not in DIRECTIONS:
        return {"error": f"direction must be one of {DIRECTIONS}"}
    if depth is not None and depth < 1:
        depth = None
    g = m.graph
    adj = g.rev if direction == "downstream" else g.edges        # downstream: source -> its readers; upstream: reader -> what it reads
    back = g.edges if direction == "downstream" else g.rev       # one link back towards the selection
    cite = _citer(snapshot_id)
    key = li_key(m, ref)
    if key is not None:
        start = {key}
        sel = {"kind": "line_item", "model": m.name, "ref": f"{key[0]}.{key[1]}", "id": cite("line_item", m.name, f"{key[0]}.{key[1]}"),
               "module": key[0], "module_id": cite("module", m.name, key[0]), "name": key[1], "formula": m.model.line_items[key].formula,
               "cells": m.model.line_items[key].cell_count}
        dist = g._closure(key, adj, depth)
    else:
        mod = module_name(m, ref)
        if mod is None:
            return {"error": f"no line item or module named {ref!r} in {m.name}"}
        start = {k for k, li in m.model.line_items.items() if k[0] == mod and not li.is_header}
        sel = {"kind": "module", "model": m.name, "ref": mod, "id": cite("module", m.name, mod), "module": mod, "module_id": cite("module", m.name, mod),
               "name": mod, "line_items": len(start)}
        raw = g._closure(_START, _WithStart(adj, start), None if depth is None else depth + 1)
        dist = {k: d - 1 for k, d in raw.items() if k not in start}
    lis = m.model.line_items
    dist = {k: d for k, d in dist.items() if k in lis and not lis[k].is_header}
    by_module: dict[str, list] = defaultdict(list)
    for k in dist:
        by_module[k[0]].append(k)
    by_dist = Counter(dist.values())

    def via(k, d):
        for p in back.get(k, ()):
            if (d == 1 and p in start) or dist.get(p) == d - 1:
                return p
        return None

    def name(k):
        return f"{k[0]}.{k[1]}"

    ordered = sorted(dist.items(), key=lambda kv: (kv[1], kv[0][0], kv[0][1]))
    nodes = []
    for k, d in ordered[:limit]:
        li = lis[k]; v = via(k, d)
        nodes.append({"ref": name(k), "id": cite("line_item", m.name, name(k)), "module": k[0], "module_id": cite("module", m.name, k[0]), "name": k[1],
                      "distance": d, "cells": li.cell_count, "effort": li.calc_effort if (m.facts or {}).get("has_effort") else None,
                      "calculated": bool(li.formula), "formula": li.formula[:120],
                      "via": {"ref": name(v), "id": cite("line_item", m.name, name(v))} if v else None})
    touched = set(by_module) | {sel["module"]}
    actions = None; unmatched: list[dict] = []
    if (m.facts or {}).get("actions"):
        steps: dict[str, list[str]] = defaultdict(list)
        for p in m.actions.processes.values():
            for s in p.steps:
                steps[s].append(p.name)
        touching = []
        for a in m.actions.actions.values():
            if a.kind not in ("import", "export"):
                continue
            procs = sorted(set(a.processes) | set(steps.get(a.name, [])))
            if a.target and a.target not in m.model.modules:
                unmatched.append({"ref": a.name, "id": cite("action", m.name, a.name), "action_kind": a.kind, "target": a.target, "processes": procs})
                continue
            if a.target in touched:
                touching.append({"ref": a.name, "id": cite("action", m.name, a.name), "action_kind": a.kind, "module": a.target,
                                 "module_id": cite("module", m.name, a.target), "direction": "writes" if a.kind == "import" else "reads",
                                 "on_selection": a.target == sel["module"], "last_run": a.last_run, "processes": procs})
        touching.sort(key=lambda a: (not a["on_selection"], a["module"], a["ref"]))
        actions = {"level": "module", "touching": touching, "unmatched": unmatched}
    feeds = []
    for e in er.edges:
        if (direction == "downstream" and e["from"] == m.name) or (direction == "upstream" and e["to"] == m.name):
            other = e["to"] if direction == "downstream" else e["from"]
            feeds.append({"model": other, "id": cite("model", other, other), "actions": e.get("actions"), "targets": list(e.get("targets") or [])[:6],
                          "phrases": list(e.get("phrases") or []), "basis": e.get("basis") or "inferred from import action names", "inferred": True})
    counts = {"line_items": len(dist), "direct": by_dist.get(1, 0), "indirect": len(dist) - by_dist.get(1, 0), "modules": len(by_module),
              "models": 1, "models_inferred": len(feeds), "actions": None if actions is None else len(actions["touching"]),
              "max_distance": max(dist.values(), default=0), "footprint_cells": sum(lis[k].cell_count for k in dist),
              "by_distance": {str(d): n for d, n in sorted(by_dist.items())}}
    modules = [{"ref": mod, "id": cite("module", m.name, mod), "line_items": len(ks), "min_distance": min(dist[k] for k in ks), "cells": sum(lis[k].cell_count for k in ks)}
               for mod, ks in sorted(by_module.items(), key=lambda kv: (min(dist[k] for k in kv[1]), -len(kv[1]), kv[0]))]
    return {"selection": sel, "direction": direction, "depth": depth, "counts": counts, "modules": modules, "nodes": nodes,
            "shown": len(nodes), "actions": actions, "feeds_inferred": feeds, "coverage": coverage_notes(m, len(unmatched)),
            "limits": ["Reach stays inside the model: the exports carry no line-item mapping across models, so other models are listed from the import names, as inferred, and never counted as line items.",
                       "Actions are linked at module level. An import into a module in reach may overwrite values there; an export from one reads them; neither says which line items."],
            "snapshot": snapshot_id}


# ---------- the graph's neighbourhood ----------

def graph(er, model: str, ref: str, snapshot_id: str | None = None, actions: bool = True, feeds: bool = True, cap: int = 80) -> dict:
    """One node with its direct neighbours, in the shape a graph grows from: line items inside their module inside
    the model (compound nodes), reference edges drawn in the direction data flows (source -> reader), import and
    export actions attached to the module they touch (module level, dashed), and other models attached to the model
    node as inferred feeds. For a module: its line items and the edges among them."""
    m = find_model(er, model)
    if m is None:
        return {"error": f"no model named {model!r}"}
    g = m.graph; lis = m.model.line_items
    cite = _citer(snapshot_id)
    model_id = cite("model", m.name, m.name)
    nodes: dict[str, dict] = {model_id: {"id": model_id, "kind": "model", "ref": m.name, "model": m.name, "label": m.name}}
    edges: dict[str, dict] = {}

    def mod_node(mod):
        mid = cite("module", m.name, mod)
        if mid not in nodes:
            nodes[mid] = {"id": mid, "kind": "module", "ref": mod, "model": m.name, "label": mod, "parent": model_id,
                          "line_items": sum(1 for k, li in lis.items() if k[0] == mod and not li.is_header)}
        return mid

    def li_node(k):
        ref = f"{k[0]}.{k[1]}"; nid = cite("line_item", m.name, ref)
        if nid not in nodes:
            li = lis[k]
            nodes[nid] = {"id": nid, "kind": "line_item", "ref": ref, "model": m.name, "module": k[0], "name": k[1], "label": k[1], "parent": mod_node(k[0]),
                          "cells": li.cell_count, "calculated": bool(li.formula), "effort": li.calc_effort if (m.facts or {}).get("has_effort") else None,
                          "uses_count": len(g.edges.get(k, ())), "used_by_count": len(g.rev.get(k, ())), "formula": li.formula[:120]}
        return nid

    def edge(src, dst, kind, **extra):
        eid = f"{src}>{dst}:{kind}"
        if eid not in edges:
            edges[eid] = {"id": eid, "source": src, "target": dst, "type": kind, **extra}

    key = li_key(m, ref)
    if key is not None:
        centre = li_node(key)
        for s in sorted(g.edges.get(key, ()))[:cap]:
            edge(li_node(s), centre, "ref")                      # data flows from what it reads into it
        for r in sorted(g.rev.get(key, ()))[:cap]:
            edge(centre, li_node(r), "ref")
        truncated = len(g.edges.get(key, ())) > cap or len(g.rev.get(key, ())) > cap
    else:
        mod = module_name(m, ref)
        if mod is None:
            return {"error": f"no line item or module named {ref!r} in {m.name}"}
        centre = mod_node(mod)
        items = [k for k, li in lis.items() if k[0] == mod and not li.is_header]
        for k in items[:cap]:
            li_node(k)
        inside = set(items[:cap])
        for k in inside:
            for s in g.edges.get(k, ()):
                if s in inside:
                    edge(li_node(s), li_node(k), "ref")
        truncated = len(items) > cap
    mods_present = [n["ref"] for n in list(nodes.values()) if n["kind"] == "module"]
    if actions and (m.facts or {}).get("actions"):
        for a in m.actions.actions.values():
            if a.kind not in ("import", "export") or a.target not in mods_present:
                continue
            aid = cite("action", m.name, a.name)
            nodes.setdefault(aid, {"id": aid, "kind": "action", "ref": a.name, "model": m.name, "label": a.name, "parent": model_id, "action_kind": a.kind,
                                   "last_run": a.last_run, "processes": list(a.processes), "level": "module"})
            mid = cite("module", m.name, a.target)
            if a.kind == "import":
                edge(aid, mid, "import", level="module")
            else:
                edge(mid, aid, "export", level="module")
    if feeds:
        for e in er.edges:
            if e["from"] == m.name or e["to"] == m.name:
                other = e["to"] if e["from"] == m.name else e["from"]
                oid = cite("model", other, other)
                nodes.setdefault(oid, {"id": oid, "kind": "model", "ref": other, "model": other, "label": other, "inferred": True})
                src, dst = (model_id, oid) if e["from"] == m.name else (oid, model_id)
                edge(src, dst, "feed", inferred=True, actions=e.get("actions"), label=f"{e.get('actions')} import{'s' if e.get('actions') != 1 else ''}, inferred")
    return {"centre": centre, "model": m.name, "nodes": list(nodes.values()), "edges": list(edges.values()), "truncated": truncated, "snapshot": snapshot_id,
            "edge_types": {"ref": "line item reads line item (parsed formula reference; evidenced); the arrow follows the data",
                           "import": "import action writes a module (module level; from the Actions export)",
                           "export": "export action reads a module (module level; from the Actions export)",
                           "feed": "model feeds model (inferred from import action names; never line-item lineage)"}}
