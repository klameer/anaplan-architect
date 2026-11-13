"""The tools the architect can call during a conversation. Each is one
question over the parsed estate; together they are the ORM the model
sees. Every result names objects exactly as the validator knows them, and
carries `cites`: name -> citation id for every object it handed over, minted
by orac.evidence and bound to the snapshot the estate was read from.
"""
from __future__ import annotations
import json
from anaplan_grammar.parser import parse, ParseError
from anaplan_grammar.unparse import unparse
from anaplan_estate.lint import RULES
from .store import Workspace, pattern_id, STATUSES
from .orac.evidence import Evidence


RESULT_CHARS = 24000        # one tool result, at most (about 6,000 tokens): counts and top rows, never a whole list


class Toolbox:
    def __init__(self, w: Workspace, ev: Evidence | None = None):
        self.w = w
        self.ev = ev if ev is not None else Evidence(w.estate_id, w.snapshot_id)   # an empty registry is still the shared one
        self.log: list[dict] = []
        self._tool = ""
        self._cites: dict[str, str] = {}
        self.results: list[tuple[str, dict, dict]] = []     # (tool, args, result) of this conversation, for the blocks the page draws
        self.sections: dict[str, dict] = {}                 # section id -> row, for every document section handed this conversation
        self.concise = False                                # a concise answer pulls fewer sections
        self.planned: set[str] = set()                      # names a build plan of this conversation creates: real to the validator, though not in the estate

    # ---------- citing helpers: return the canonical name, record the id ----------
    def _model(self, name: str) -> str:
        self._cites[name] = self.ev.mint("model", name, name, name, self._tool).id
        return name

    def _mod(self, m, mod: str) -> str:
        self._cites[mod] = self.ev.mint("module", m.name, mod, mod, self._tool).id
        return mod

    def _li(self, m, key) -> str:
        name = f"{key[0]}.{key[1]}"
        self._cites[name] = self.ev.mint("line_item", m.name, name, name, self._tool).id
        return name

    def _act(self, m, name: str) -> str:
        self._cites[name] = self.ev.mint("action", m.name, name, name, self._tool).id
        return name

    def _pat(self, m, pid: str) -> str:
        self._cites[pid] = self.ev.mint("pattern", m.name, pid, pid, self._tool).id
        return pid

    def _rule(self, rid: str) -> str:
        self._cites[rid] = self.ev.mint("finding", "", rid, rid, self._tool).id
        return rid

    def _li_dict(self, m, li) -> dict:
        return {"model": self._model(m.name), "object": self._li(m, li.key), "module": self._mod(m, li.module), "line_item": li.name, "formula": li.formula,
                "format": li.format_type, "applies_to": list(li.applies_to), "time_scale": li.time_scale, "versions": li.versions, "summary": li.summary,
                "cells": li.cell_count, "calc_effort_pct": li.calc_effort, "notes": li.notes}

    # ---------- the tools ----------
    def list_models(self) -> dict:
        return {"models": [{"name": self._model(m.name), "modules": m.facts["modules"], "line_items": m.facts["line_items"], "cells": m.facts["cells"],
                            "imports": (m.facts["actions"] or {}).get("imports"), "patterns": m.facts["patterns"]} for m in self.w.estate.models],
                "edges": [dict(e, **{"from": self._model(e["from"]), "to": self._model(e["to"])},
                               state=(st["state"] if st else "inferred"), reason=(st or {}).get("reason", ""), by=(st or {}).get("by"), when=(st or {}).get("when"))
                          for e in self.w.estate.edges for st in [self.w.edge_state(e["from"], e["to"])]],
                "note": "a feed is read off the import action names and is inferred until the owner confirms it (real and used) or retires it (the import survives, the feed is dead)"}

    def set_edge_state(self, from_model: str, to_model: str, state: str, reason: str) -> dict:
        """The owner's word on a feed between two models. Only a feed the import names show can be confirmed or retired."""
        names = {m.name.lower(): m.name for m in self.w.estate.models}
        f, t = names.get((from_model or "").lower()), names.get((to_model or "").lower())
        if not f or not t:
            return {"error": "both ends must be models of this estate", "models": list(names.values())}
        if not any(e["from"] == f and e["to"] == t for e in self.w.estate.edges):
            return {"error": f"the exports show no import from {f} into {t}: only a feed the import names show can be confirmed or retired"}
        if state not in ("confirmed", "retired", "inferred"):
            return {"error": "state must be confirmed, retired or inferred"}
        try:
            rec = self.w.set_edge_state(f, t, state, reason, by="chat")
        except ValueError as e:
            return {"error": str(e)}
        return {"from": self._model(f), "to": self._model(t), "set": rec or {"state": "inferred"}}

    def find(self, text: str, model: str | None = None, limit: int = 20) -> dict:
        t = text.lower(); hits = []
        for m in self.w.estate.models:
            if model and m.name != model:
                continue
            for (mod, li), obj in m.model.line_items.items():
                if obj.is_header:
                    continue
                if t in li.lower() or t in mod.lower() or t in obj.formula.lower():
                    hits.append({"model": self._model(m.name), "object": self._li(m, (mod, li)), "cells": obj.cell_count,
                                 "in": "name" if t in li.lower() else "module" if t in mod.lower() else "formula"})
                    if len(hits) >= limit:
                        return {"hits": hits, "truncated": True}
        return {"hits": hits, "truncated": False}

    def get_object(self, name: str, model: str | None = None) -> dict:
        kind, m, obj = self.w.find_object(name, model)
        if kind is None:
            return {"error": f"no object named {name!r}" + (f" in {model}" if model else "")}
        if kind == "ambiguous":
            return {"error": "ambiguous", "candidates": [self._li(m, o.key) for o in obj[:10]]}
        if kind == "module":
            lis = m.model.by_module(obj.name)
            return {"model": self._model(m.name), "module": self._mod(m, obj.name), "applies_to": list(obj.applies_to), "line_items": len(lis),
                    "cells": obj.cell_count or sum(x.cell_count for x in lis), "notes": obj.notes,
                    "items": [{"object": self._li(m, x.key), "name": x.name, "formula": x.formula[:120], "cells": x.cell_count} for x in lis[:60]]}
        g = m.graph; k = obj.key
        d = self._li_dict(m, obj)
        d["uses"] = [self._li(m, t) for t in sorted(g.edges.get(k, ()))][:40]
        d["used_by"] = [self._li(m, t) for t in sorted(g.rev.get(k, ()))][:40]
        d["used_by_count"] = len(g.rev.get(k, ()))
        d["parse_error"] = g.parse_errors.get(k)
        return d

    def explain(self, name: str, model: str | None = None) -> dict:
        kind, m, obj = self.w.find_object(name, model)
        if kind != "line_item":
            return {"error": f"need a line item, got {kind}"}
        me = self._li(m, obj.key)
        if not obj.formula:
            return {"object": me, "model": self._model(m.name), "kind": "input", "note": "no formula: an input or an import target"}
        try:
            tree = parse(obj.formula)
        except ParseError as e:
            return {"object": me, "model": self._model(m.name), "error": f"parse failed: {e}"}
        refs = [{"path": ".".join(r.path), "kind": r.kind, "resolves_to": self._li(m, r.target) if r.target else None} for r in m.graph.refs.get(obj.key, [])]
        return {"object": me, "model": self._model(m.name), "formula": obj.formula, "tree": tree, "references": refs, "normalised": unparse(tree)}

    def impact(self, name: str, model: str | None = None, direction: str = "downstream", depth: int | None = None) -> dict:
        """The reach of a change to a line item or a module, as the Dependencies page counts it: every line item once at its
        shortest distance (the selection excluded, a cycle never counted twice), rolled up to modules, actions at module level
        (imports that write into a module in reach, exports that read one), other models apart as inferred from import names
        unless the owner has confirmed or retired the feed, and the coverage gaps beside every count."""
        from .orac import deps as depsmod
        kind, m, obj = self.w.find_object(name, model)
        if kind == "ambiguous":
            return {"error": "ambiguous", "candidates": [self._li(m, o.key) for o in obj[:10]]}
        if kind not in ("line_item", "module"):
            return {"error": f"need a line item or a module, got {kind}"}
        ref = f"{obj.module}.{obj.name}" if kind == "line_item" else obj.name
        direction = direction if direction in ("downstream", "upstream") else "downstream"
        r = depsmod.reach(self.w.estate, m.name, ref, direction, depth=depth, snapshot_id=self.w.snapshot_id, limit=400)
        if "error" in r:
            return r
        self._model(m.name)
        self._li(m, obj.key) if kind == "line_item" else self._mod(m, ref)
        mods = r["modules"][:30]
        for mod in mods:
            self._mod(m, mod["ref"])
        nodes = r["nodes"][:40]
        for n in nodes:
            self._li(m, (n["module"], n["name"]))
        acts = r.get("actions")
        touching, unmatched = [], []
        if acts:
            for a in acts["touching"][:20]:
                self._act(m, a["ref"]); self._mod(m, a["module"])
                touching.append({k: a[k] for k in ("ref", "action_kind", "module", "direction", "on_selection", "last_run")})
            for a in acts["unmatched"][:10]:
                self._act(m, a["ref"])
                unmatched.append({"ref": a["ref"], "action_kind": a["action_kind"], "target": a["target"]})
        others = []
        for f in r["feeds_inferred"]:
            self._model(f["model"])
            st = self.w.edge_state(m.name, f["model"]) if direction == "downstream" else self.w.edge_state(f["model"], m.name)
            others.append({"model": f["model"], "actions": f["actions"], "targets": f["targets"], "basis": f["basis"],
                           "state": st["state"] if st else "inferred", "reason": (st or {}).get("reason", "")})
        return {"selection": r["selection"]["ref"], "kind": kind, "model": m.name, "direction": direction, "depth": r["depth"],
                "counts": r["counts"], "coverage": r["coverage"], "limits": r["limits"],
                "modules": [{k: v for k, v in mod.items() if k != "id"} for mod in mods], "modules_total": len(r["modules"]),
                "line_items": [{"ref": n["ref"], "distance": n["distance"], "via": (n.get("via") or {}).get("ref"), "cells": n["cells"],
                                "formula": n["formula"]} for n in nodes], "line_items_shown": len(nodes),
                "actions": ({"level": "module", "touching": touching, "unmatched": unmatched} if acts else None),
                "other_models": others,
                "note": "counts are over the whole reach unless depth is given: every line item once at its shortest distance, the selection excluded; "
                        "actions are linked at module level; other models are inferred from import names unless the owner has confirmed or retired the feed"}

    def lineage(self, name: str, model: str | None = None, depth: int = 4) -> dict:
        kind, m, obj = self.w.find_object(name, model)
        if kind != "line_item":
            return {"error": f"need a line item, got {kind}"}
        lin = m.graph.lineage(obj.key, depth)
        inputs = [self._li(m, key) for key in lin if not m.model.line_items[key].formula]
        return {"object": self._li(m, obj.key), "model": self._model(m.name), "upstream_line_items": len(lin),
                "chain": [{"object": self._li(m, key), "distance": d, "formula": m.model.line_items[key].formula[:100]}
                          for key, d in sorted(lin.items(), key=lambda kv: kv[1])[:40]],
                "input_line_items": inputs[:30]}

    def list_patterns(self, model: str | None = None, rule: str | None = None, status: str | None = None, limit: int = 40) -> dict:
        out = []
        for m in self.w.estate.models:
            if model and m.name != model:
                continue
            for c in m.clusters:
                pid = pattern_id(m, c); st = self.w.status_of(pid)
                if (rule and c.rule != rule) or (status and st != status):
                    continue
                out.append({"id": self._pat(m, pid), "model": self._model(m.name), "rule": self._rule(c.rule), "severity": c.severity, "count": c.count,
                            "label": c.label, "status": st, "example": c.objects[0] if c.objects else ""})
                if len(out) >= limit:
                    return {"patterns": out, "truncated": True}
        return {"patterns": out, "truncated": False}

    def get_pattern(self, id: str) -> dict:
        for m in self.w.estate.models:
            for c in m.clusters:
                pid = pattern_id(m, c)
                if pid == id:
                    return {"id": self._pat(m, pid), "model": self._model(m.name), "rule": self._rule(c.rule), "title": RULES[c.rule].title,
                            "severity": c.severity, "count": c.count, "modules": [self._mod(m, x) for x in c.modules[:20]], "objects": c.objects,
                            "message": c.message, "fix": c.fix, "status": self.w.statuses.get(pid, {"status": "open"}), "planual": list(RULES[c.rule].planual)}
        return {"error": f"no pattern {id!r}"}

    def rule(self, id: str) -> dict:
        r = RULES.get(id)
        if not r:
            return {"error": f"no rule {id!r}", "rules": list(RULES)}
        return {"id": self._rule(r.id), "title": r.title, "severity": r.severity, "source": r.source, "description": r.description,
                "thresholds": r.thresholds, "planual": list(r.planual)}

    def actions(self, model: str, target: str | None = None) -> dict:
        m = self.w.models().get(model)
        if not m:
            return {"error": f"no model {model!r}"}
        acts = [a for a in m.actions.actions.values() if not target or (a.target and target.lower() in a.target.lower()) or target.lower() in a.name.lower()]
        return {"model": self._model(model),
                "actions": [{"name": self._act(m, a.name), "kind": a.kind, "target": self._mod(m, a.target) if a.target and a.target in m.model.modules else a.target,
                             "last_run": a.last_run, "duration_ms": a.duration_ms, "processes": [self._act(m, p) for p in a.processes]} for a in acts[:60]],
                "facts": m.facts["actions"]}

    def validate_formula(self, formula: str, model: str, module: str) -> dict:
        """Parse a proposed formula and resolve every reference against the model, as the graph would."""
        m = self.w.models().get(model)
        if not m:
            return {"error": f"no model {model!r}"}
        if module not in m.model.modules:
            return {"error": f"no module {module!r} in {model}"}
        try:
            tree = parse(formula)
        except ParseError as e:
            return {"ok": False, "parse_error": str(e)}
        from anaplan_estate.model import LineItem
        probe = LineItem(module=module, name="__proposed__", formula=formula)
        from anaplan_grammar.parser import references
        unresolved, resolved = [], []
        from anaplan_estate.graph import PSEUDO_LISTS
        for path in references(tree):
            r = m.graph.resolve(probe, list(path))
            kind = r.kind
            if kind == "list_item" and path[0] not in m.model.dimensions and path[0].upper() not in PSEUDO_LISTS:
                kind = "unresolved"        # Module.Item where neither a module nor a known list: invented
            (resolved if kind != "unresolved" else unresolved).append({"path": ".".join(path), "kind": kind, "target": self._li(m, r.target) if r.target else None})
        return {"ok": not unresolved, "model": self._model(model), "module": self._mod(m, module), "normalised": unparse(tree), "resolved": resolved, "unresolved": unresolved,
                "note": "unresolved may be list items or dimensions the exports do not carry; check those by hand"}

    def set_status(self, pattern: str, status: str, reason: str) -> dict:
        if status not in STATUSES:
            return {"error": f"status must be one of {STATUSES}"}
        hit = next(((m, c) for m in self.w.estate.models for c in m.clusters if pattern_id(m, c) == pattern), None)
        if not hit:
            return {"error": f"no pattern {pattern!r}"}
        return {"pattern": self._pat(hit[0], pattern), "set": self.w.set_status(pattern, status, reason, by="chat")}

    def remember(self, scope: str, text: str) -> dict:
        if not (scope == "estate" or scope.startswith("model:") or scope.startswith("rule:")):
            return {"error": "scope must be 'estate', 'model:<name>' or 'rule:<RULE-ID>'"}
        # Text in a document, an export's notes column or a tool result may be aimed at the assistant. A note it keeps in
        # a chat that had read project documents says so in its title, where the owner and every later prompt see it.
        after = "Kept by the assistant after reading project documents: unconfirmed" if self.sections else ""
        return {"remembered": self.w.remember(scope, text, by="chat", title=after),
                "note": "kept as the assistant's own working assumption, not the owner's word, until the owner confirms it"}

    # ---------- the action plan (stage 4) ----------
    def _obj(self, m, name: str) -> str:
        """A card's object as the validator knows it: a line item when 'Module.Line Item' is one, else a module, else as written."""
        key = next((k for k in m.model.line_items if f"{k[0]}.{k[1]}" == name), None)
        if key is not None:
            return self._li(m, key)
        if name in m.model.modules:
            return self._mod(m, name)
        return name

    def action_plan(self, model: str | None = None, include_below_bar: bool = False) -> dict:
        """The plan over this parse (the first few candidates that met the bar) with the owner's decisions, and the proposals
        kept beside it; with include_below_bar, every other candidate too, each with the reason it is not on the plan."""
        from anaplan_estate import plan as eplan
        from .orac.findings_state import ACTION_STATES
        sel = eplan.select(self.w.estate)
        b = self.w.backend
        states = b.action_states() if b is not None else {}
        runs = self.w.models()
        plan = {c["key"] for c in sel["actions"]}
        out = []
        for c in sel["candidates"]:
            if model and c["model"] != model:
                continue
            if not include_below_bar and c["key"] not in plan:
                continue
            st = states.get("action:" + c["key"]) or {}
            m = runs.get(c["model"])
            out.append({"key": c["key"], "rank": c["rank_reason"].split(":")[0], "kind": c["kind"], "on_plan": c["key"] in plan, "tests": c.get("tests") or [], "title": c["title"],
                        "model": self._model(c["model"]), "objects": [self._obj(m, o) for o in c["objects"][:8]] if m else c["objects"][:8],
                        "met_bar": c["worth"], "why_not": c["why_not"], "state": st.get("state", "to_review"), "state_reason": st.get("reason", ""),
                        "footprint_cells": c["footprint_cells"], "footprint_effort": c["footprint_effort"], "strength": c["strength"],
                        "done_when": c["done_when"], "notices": c["notices"][:3], "depends_on": c["depends_on"]})
        props = []
        for p in (b.proposals() if b is not None else []):
            st = states.get("proposal:" + p["id"]) or {}
            props.append({"id": p["id"], "title": p["title"], "model": p["model"], "origin": p["origin_kind"], "state": st.get("state", "unconfirmed"), "objects": p["objects"][:8]})
        return {"actions": out, "top": sel["top"], "considered": sel["considered"], "met_bar": sel["met_bar"], "proposals": props, "none": sel["none"], "states": list(ACTION_STATES),
                "note": "the plan is the first candidates that met the bar, picked from the results of every test and ranked as the report ranks them "
                        "(on_plan); any other candidate carries why_not, the reason it is not on the plan; states are the owner's recorded decisions; "
                        "a proposal is unconfirmed until the owner takes it on; a state verifies nothing in Anaplan"}

    def tests(self, status: str | None = None, area: int | None = None, number: str | None = None) -> dict:
        """The catalogue of tests with the result of each on this parse: found, clear, or not run and why."""
        from .orac import checks as checksmod
        every = checksmod.of(self.w)
        rows = every
        if number:
            rows = [r for r in rows if r["num"] == str(number).strip()]
            if not rows:
                return {"error": f"no test numbered {number!r}", "numbers": [r["num"] for r in every]}
        if status:
            want = str(status).strip().lower().replace("_", " ")
            if want not in checksmod.STATUSES:
                return {"error": f"status must be one of found, clear, not_run; got {status!r}"}
            rows = [r for r in rows if r["status"] == want]
        if area:
            rows = [r for r in rows if r["category"] == int(area)]
        full = bool(number) or len(rows) <= 12                  # a short list carries what each test looks for and what it needs
        out = []
        for r in rows:
            d = {"test": r["num"], "key": r["key"], "area": r["category"], "title": r["title"], "status": r["status"], "hits": r["hits"]}
            if r["by_model"]:
                d["by_model"] = [{"model": self._model(p["model"]), "hits": p["hits"], "cells": p["cells"], "effort_pct": p["effort"]} for p in r["by_model"]]
            if r["not_run"]:
                d["not_run"] = r["not_run"]
            if r["rules"]:
                d["rules"] = [self._rule(x) for x in r["rules"]]
            if r["findings"]:
                d["findings"] = [f["id"] + " " + f["title"] for f in r["findings"][:6]]
            if full:
                d["what"] = r["what"]; d["needs"] = r["needs"]
            out.append(d)
        roll = checksmod.rollup(every)
        return {"tests": out, "total": roll["total"], "found": roll["found"], "clear": roll["clear"], "not_run": roll["not_run"],
                "areas": [{"area": a["num"], "title": a["title"], "tests": a["total"], "found": a["found"], "clear": a["clear"], "not_run": a["not_run"]} for a in roll["areas"]],
                "note": checksmod.NOTE}

    def propose_action(self, title: str, why: str, steps: str, done_when: str, model: str, objects: str) -> dict:
        """Keep a suggestion on the Action plan as the architect's proposal, shown apart from the deterministic cards and unconfirmed."""
        from .orac import plan as planmod
        if self.w.backend is None:
            return {"error": "no store: proposals live in the web app's store"}
        m = self.w.models().get(model)
        if not m:
            return {"error": f"no model {model!r}"}
        names = [o.strip() for o in (objects or "").split(",") if o.strip()]
        try:
            canon = planmod.check_objects(self.w.estate, m.name, names)
        except ValueError as e:
            return {"error": str(e), "note": "name only objects that exist in the model, as 'Module.Line Item' or a module name"}
        for o in canon:
            self._obj(m, o)
        ids = [self._cites[o] for o in canon if o in self._cites]
        rec = self.w.backend.propose(title, why, [s for s in (steps or "").splitlines()], done_when, self._model(m.name), canon, ids, by="chat")
        self.w.__dict__.pop("_handles", None)         # proposal:<id> is a handle the validator must know from this turn on
        return {"proposal": rec["id"], "title": rec["title"], "objects": canon, "state": "unconfirmed",
                "note": "shown on the Action plan as the architect's proposal until the owner takes it on"}

    def set_action_state(self, key: str, state: str, reason: str) -> dict:
        """The owner's decision on an action of the plan (a deterministic key, or proposal:<id>)."""
        from anaplan_estate import plan as eplan
        from .orac.findings_state import ACTION_STATES
        if state not in ACTION_STATES:
            return {"error": f"state must be one of {ACTION_STATES}"}
        if self.w.backend is None:
            return {"error": "no store"}
        k = key if key.startswith(("action:", "proposal:", "size:")) else "action:" + key
        if k.startswith("size:"):                                              # an over-dimensioned line item of the Size page
            model, _, ref = k[5:].partition("::")
            kind, mm, obj = self.w.find_object(ref, model or None)
            if kind != "line_item" or (model and mm.name.lower() != model.lower()):
                return {"error": f"no line item {ref!r} in {model!r}: a size key is size:<model>::<Module.Line Item> as the size tool returned it"}
            k = "size:" + mm.name + "::" + f"{obj.module}.{obj.name}"
            self._li(mm, obj.key)
            return {"set": self.w.backend.set_action_state(k, state, reason, by="chat")}
        valid = {"action:" + c["key"] for c in eplan.select(self.w.estate)["candidates"]} | {"proposal:" + p["id"] for p in self.w.backend.proposals()}
        if k not in valid:
            return {"error": f"no action {key!r} on the plan", "keys": sorted(valid)[:40]}
        return {"set": self.w.backend.set_action_state(k, state, reason, by="chat")}

    # ---------- size: dimension inference and cell cost (Orac backlog 18) ----------
    def _dims(self, m):
        from .orac.dims import ModelDims
        cache = self.w.__dict__.setdefault("_dims", {})
        md = cache.get(m.name)
        if md is None:
            md = cache[m.name] = ModelDims(m, self.w.snapshot_id)
        return md

    def size(self, model: str | None = None, name: str | None = None) -> dict:
        """What a model's cells are made of: sizes solved from cell counts (lists, time ranges, versions, with how many line
        items agree), what each axis costs, the over-dimensioned line items priced; or one line item's applied versus required axes."""
        from .orac.dims import summarize_for_tool
        from .orac.findings_state import size_key
        ms = self.w.estate.models
        m = None
        if model:
            m = next((x for x in ms if x.name == model), None) or next((x for x in ms if x.name.lower() == model.lower()), None)
            if m is None:
                return {"error": f"no model named {model!r}", "models": [x.name for x in ms]}
        if name:
            kind, mm, obj = self.w.find_object(name, m.name if m else None)
            if kind == "ambiguous":
                return {"error": "ambiguous", "candidates": [self._li(mm, o.key) for o in obj[:10]]}
            if kind != "line_item":
                return {"error": f"no line item named {name!r}" + (f" in {m.name}" if m else "")}
            j = self._dims(mm).item(f"{obj.module}.{obj.name}")
            self._li(mm, obj.key); self._model(mm.name)
            key = size_key(mm.name, j["ref"]); d = self._size_states().get(key)
            return {k: v for k, v in j.items() if k not in ("id", "snapshot")} | {"model": mm.name, "key": key,
                    "decision": ({"state": d["state"], "reason": d["reason"], "by": d.get("by"), "when": d.get("updated")} if d else None)}
        if m is None:
            m = max(ms, key=lambda x: (x.facts.get("cells") or 0, x.name))
        return summarize_for_tool(self._dims(m), lambda mod, li: self._li(m, (mod, li)), lambda n: self._model(n), states=self._size_states(),
                                  cite_module=lambda mod: self._mod(m, mod))

    def _size_states(self) -> dict:
        return self.w.backend.size_states() if self.w.backend is not None else {}

    # ---------- project documents (v0.2 P1): cards are always in context, sections are pulled ----------
    def _docs(self):
        b = self.w.backend
        if b is None:
            return None, None
        return b.db, b.estate_id

    def _section_cite(self, sid: str, title: str, heading: str) -> str:
        self._cites[sid] = self.ev.mint("document", "", sid, f"{title} · {heading}" if heading else title, self._tool, provenance="observed").id
        return sid

    def search_documents(self, query: str = "", objects: str = "", document: str | None = None, limit: int = 6) -> dict:
        """Section hits across the workspace's project documents: keyword search over headings and text, plus every section
        that names one of the given objects. Snippets only; get_section reads one."""
        from .orac import documents as docsmod
        db, eid = self._docs()
        if db is None:
            return {"error": "project documents live in the web app's store"}
        names = [o.strip() for o in (objects or "").split(",") if o.strip()]
        if not (query or "").strip() and not names:
            return {"error": "give a query, or objects (comma-separated module or 'Module.Line Item' names), or both"}
        r = docsmod.search(db, eid, query, names, document, min(int(limit or 6), 3 if self.concise else 8))
        for h in r["hits"]:
            self._section_cite(h["section"], h["document"], h["heading"])
            row = docsmod.get_section(db, h["section"], eid)
            if row:
                self.sections[h["section"]] = row
        r["note"] = ("snippets, not sections: call get_section for the ones that bear on the question before you quote or rely on one. "
                     "No hit means no document here covers it: say it is not recorded, never fill it in.")
        return r

    def get_section(self, section: str) -> dict:
        """One section of a project document, in full, with the objects it names. Quote from it word for word."""
        from .orac import documents as docsmod
        db, eid = self._docs()
        if db is None:
            return {"error": "project documents live in the web app's store"}
        row = docsmod.get_section(db, (section or "").strip(), eid)
        if row is None:
            return {"error": f"no section {section!r} in this workspace: use an id search_documents returned"}
        self.sections[row["id"]] = row
        self._section_cite(row["id"], row["doc_title"], row["heading"])
        return {"section": row["id"], "document": row["doc_title"], "type": row["doc_type"], "date": row["doc_date"], "heading": row["heading"],
                "position": f"section {row['seq'] + 1} of {row['of']}", "text": row["text"], "names": [o["ref"] for o in row["objects"]],
                "note": "quote the passage you rely on word for word in double quotes and write this section id in backticks right after it"}

    # ---------- the line-item index (v0.2 P2): exact counts and filters across every model ----------
    def query_line_items(self, model: str | None = None, module: str | None = None, function: str | None = None, references: str | None = None,
                         referenced_by: str | None = None, dimension: str | None = None, format: str | None = None, text: str | None = None,
                         calculated: bool | None = None, unreferenced: bool | None = None, min_cells: int | None = None, min_formula_length: int | None = None,
                         min_ifs: int | None = None, summary: str | None = None, group_by: str | None = None, sort: str = "cells", limit: int = 10) -> dict:
        """Count and filter line items across the workspace from the index: by function used, by what they reference or what
        references them, by dimension, format, module or model, by text. Returns the exact count, cells, a breakdown and the
        first rows, never the whole list."""
        from .orac import lindex
        b = self.w.backend
        if b is None:
            return {"error": "the line-item index lives in the web app's store"}
        lindex.ensure(b.db, self.w.snapshot_id, self.w.estate)
        if model:
            names = {m.name.lower(): m.name for m in self.w.estate.models}
            if model.lower() not in names:
                return {"error": f"no model named {model!r}", "models": list(names.values())}
            model = names[model.lower()]
        r = lindex.query(b.db, self.w.snapshot_id, model=model, module=module, function=function, references=references, referenced_by=referenced_by,
                         dimension=dimension, format=format, text=text, calculated=calculated, unreferenced=unreferenced, min_cells=min_cells,
                         min_formula_length=min_formula_length, min_ifs=min_ifs, summary=summary, group_by=group_by, sort=sort, limit=limit)
        if "error" in r:
            return r
        runs = self.w.models()
        for name in r["by_model"]:
            self._model(name)
        for row in r["rows"]:
            m = runs.get(row["model"])
            if m is not None:
                self._li(m, (row["module"], row["name"])); self._mod(m, row["module"])
        r["filters"] = {k: v for k, v in dict(model=model, module=module, function=function, references=references, referenced_by=referenced_by, dimension=dimension,
                                              format=format, text=text, calculated=calculated, unreferenced=unreferenced, min_cells=min_cells,
                                              min_formula_length=min_formula_length, min_ifs=min_ifs, summary=summary).items() if v not in (None, "")}
        return r

    # ---------- a build plan, checked by code (v0.2 P3) ----------
    def build_plan(self, model: str, title: str, modules: list, changes: list | None = None, checks_after: list | None = None, lists: list | None = None) -> dict:
        """Check a proposed build against the model: every formula is parsed, every reference resolved against the model
        and the plan's own new objects, and the modules and line items sorted into build order. A plan with a formula that
        does not parse, a reference that resolves to nothing, or a cycle is rejected with what to fix."""
        from .orac import buildplan
        names = {m.name.lower(): m for m in self.w.estate.models}
        m = names.get((model or "").lower())
        if m is None:
            return {"error": f"no model named {model!r}", "models": [x.name for x in self.w.estate.models]}
        if isinstance(modules, str):
            try:
                modules = json.loads(modules)
            except ValueError:
                return {"error": "modules must be a list of {name, applies_to, note, line_items: [{name, format, summary, formula}]}"}
        for label, val in (("changes", changes), ("checks_after", checks_after), ("lists", lists)):
            if isinstance(val, str):
                try:
                    val = json.loads(val) if val.strip() else []
                except ValueError:
                    return {"error": f"{label} must be a list"}
                if label == "changes":
                    changes = val
                elif label == "lists":
                    lists = val
                else:
                    checks_after = val
        r = buildplan.check(m, modules, title or "", changes=changes, checks_after=checks_after, lists=lists)
        if not r["ok"]:
            return {"ok": False, "rejected": r["rejected"][:30], "note": "nothing was accepted: fix every item listed and call build_plan again with the whole plan. "
                    "Look an existing object up (get_object, find, query_line_items) before you refer to it; write a reference to another module as 'Module Name'.Line Item. "
                    "An existing line item is changed under changes (its whole new formula), never under a module's line_items."}
        plan = r["plan"]
        self._model(m.name)
        for name in plan["existing"]:
            if name in m.model.modules:
                self._mod(m, name)
        for mod in plan["modules"]:
            if mod["state"] != "new":
                self._mod(m, mod["name"])
            self.planned.add(mod["name"].lower())
            for it in mod["items"]:
                self.planned.add(f"{mod['name']}.{it['name']}".lower()); self.planned.add(it["name"].lower())
                for ref in it["refs"]:
                    if ref.get("module") and not ref.get("new") and (ref["module"], ref["path"].split(".")[-1]) in m.model.line_items:
                        self._li(m, (ref["module"], ref["path"].split(".")[-1]))
        for d in plan.get("new_lists") or []:          # a list the plan creates is a name the answer may use
            self.planned.add(d.lower())
        for ch in plan["changes"]:
            self._li(m, (ch["module"], ch["name"]))
            for ref in ch["refs"]:
                if ref.get("module") and not ref.get("new") and (ref["module"], ref["path"].split(".")[-1]) in m.model.line_items:
                    self._li(m, (ref["module"], ref["path"].split(".")[-1]))
        c = plan["checks"]
        return {"ok": True, "plan": plan,
                "summary": {"modules": [f"{x['step']}. {x['name']} ({x['state']}, {len(x['items'])} line items)" for x in plan["modules"]], "formulas_parsed": f"{c['parsed']} of {c['formulas']}",
                            "references": f"{c['refs_existing']} to the model, {c['refs_new']} to this plan", "order": "no cycle; each step reads only the model as it is or earlier steps",
                            "existing_formulas_changed": [f"{x['module']}.{x['name']}" for x in plan["changes"]], "builder_steps": len(plan["steps"])},
                "note": "the page draws this plan from this result (what is built, what it uses, the line items, the numbered steps): do not retype modules, line items, formulas or steps. "
                        "Write the Brief as the overview: three or four plain sentences on what will be built and why, and what it replaces. Nothing has been built in Anaplan."}

    # ---------- dispatch and schema ----------
    def call(self, name: str, args: dict, max_chars: int | None = None) -> str:
        fn = getattr(self, name, None)
        self._tool = name; self._cites = {}
        if not fn or name.startswith("_") or name in ("call", "schema", "log", "ev", "w"):
            res = {"error": f"no tool {name!r}"}
        else:
            try:
                res = fn(**args)
            except TypeError as e:                          # the wrong arguments: the schema says what it wanted
                res = {"error": str(e)}
            except Exception as e:                          # anything else a tool raises is an answer to the model, never a break in the
                res = {"error": f"{type(e).__name__}: {e}"[:600]}   # loop: an assistant turn holding a tool_use with no tool_result poisons every later call
        if isinstance(res, dict) and self._cites:
            res["cites"] = dict(self._cites)
        out = json.dumps(res, default=str, ensure_ascii=False)
        full = len(out)
        cap = min(RESULT_CHARS, max_chars) if max_chars is not None else RESULT_CHARS
        if full > cap:                                      # the context budget is enforced here: counts and top rows, never a whole list
            keep = max(400, cap - 400)
            out = json.dumps({"truncated": True, "kept_chars": keep, "of_chars": full,
                              "note": "this result was cut to fit the context budget of the answer: ask this tool for less (one model, one module, a smaller limit) rather than relying on the cut part",
                              "partial": out[:keep]}, ensure_ascii=False)
        if isinstance(res, dict):
            self.results.append((name, args, res))
        self.log.append({"tool": name, "args": args, "result_chars": len(out), "full_chars": full, "truncated": full > cap, "cites": len(self._cites),
                         "error": res.get("error") if isinstance(res, dict) else None})
        return out

    @staticmethod
    def schema() -> list[dict]:
        S = lambda **p: {"type": "object", "properties": {k: {"type": v[0], "description": v[1]} for k, v in p.items()}, "required": [k for k, v in p.items() if len(v) < 3]}
        return [
            {"name": "list_models", "description": "The models in the estate with sizes, and the feeds between them: each read off the import action names and inferred until the owner has confirmed or retired it (state and reason shown). Call first.", "input_schema": S()},
            {"name": "set_edge_state", "description": "Record the owner's word on a feed between two models: confirmed (real and used), retired (the import survives, the feed is dead) or inferred (back to the import names), with their reason. Only when the owner says so.", "input_schema": S(from_model=("string", "the model the feed comes from"), to_model=("string", "the model it goes into"), state=("string", "confirmed | retired | inferred"), reason=("string", "the owner's why"))},
            {"name": "find", "description": "Search line items by name, module or formula text. Use to locate an object before get_object.", "input_schema": S(text=("string", "substring"), model=("string", "restrict to one model", 0), limit=("integer", "max hits", 0))},
            {"name": "get_object", "description": "A line item (formula, dimensions, cells, effort, notes, uses, used by) or a module (its line items).", "input_schema": S(name=("string", "'Module.Line Item', a unique line item name, or a module name"), model=("string", "model name", 0))},
            {"name": "explain", "description": "Parse a line item's formula: the tree, every reference and what it resolves to.", "input_schema": S(name=("string", "'Module.Line Item'"), model=("string", "model name", 0))},
            {"name": "impact", "description": "The reach of a change to a line item or a module, as the Dependencies page counts it: every line item downstream once at its shortest distance, rolled up to modules, imports and exports at module level, other models apart (inferred from import names unless the owner confirmed or retired the feed), coverage gaps beside every count. direction=upstream for everything it depends on.", "input_schema": S(name=("string", "'Module.Line Item' or a module name"), model=("string", "model name", 0), direction=("string", "downstream (default) | upstream", 0), depth=("integer", "hops; default the whole reach", 0))},
            {"name": "lineage", "description": "Everything upstream of a line item back to the inputs: where a number comes from.", "input_schema": S(name=("string", "'Module.Line Item'"), model=("string", "model name", 0), depth=("integer", "hops, default 4", 0))},
            {"name": "list_patterns", "description": "Rule findings grouped into patterns, with their status (open, accepted, deliberate, wont_fix, incorrect, fixed).", "input_schema": S(model=("string", "model name", 0), rule=("string", "rule id such as F-DIVIDE-FN", 0), status=("string", "filter by status", 0), limit=("integer", "max", 0))},
            {"name": "get_pattern", "description": "One pattern in full: members, message, fix, Planual references, status.", "input_schema": S(id=("string", "pattern id as listed"))},
            {"name": "rule", "description": "A lint rule's text, threshold, source and Planual reference.", "input_schema": S(id=("string", "rule id"))},
            {"name": "actions", "description": "Imports, exports and processes of a model, optionally filtered by target module or name.", "input_schema": S(model=("string", "model name"), target=("string", "module or name substring", 0))},
            {"name": "validate_formula", "description": "Parse a proposed formula and resolve its references against a model, before showing it to the owner. Always call before proposing a formula.", "input_schema": S(formula=("string", "the formula text"), model=("string", "model name"), module=("string", "module the line item would live in"))},
            {"name": "set_status", "description": "Record the owner's decision on a pattern with their reason. Only when the owner says so.", "input_schema": S(pattern=("string", "pattern id"), status=("string", "accepted | deliberate | wont_fix | incorrect | fixed | open"), reason=("string", "the owner's why"))},
            {"name": "remember", "description": "Keep something the owner told you for future runs. Only when the owner gives a reason worth keeping.", "input_schema": S(scope=("string", "estate | model:<name> | rule:<RULE-ID>"), text=("string", "the fact, in one or two sentences"))},
            {"name": "action_plan", "description": "The action plan: the first five candidates that met the bar, picked from the results of every test and ranked as the report ranks them, each with the owner's state (to_review, investigating, done, keep_current_design), plus proposals kept beside it. Call when the owner asks what to do first or for a plan.", "input_schema": S(model=("string", "restrict to one model", 0), include_below_bar=("boolean", "also every candidate that is not on the plan, each with why_not: met the bar but ranked lower, or fell below it", 0))},
            {"name": "tests", "description": "The tests run on this parse, the numbered catalogue the report runs: each with its result (found, clear, or not run and why), the hits per model with their cells and effort share, the rules behind it and the findings it produced. Call when the owner asks what was checked, what came back clear, what could not be run, or which test raised something.", "input_schema": S(status=("string", "found | clear | not_run", 0), area=("integer", "1 performance and size, 2 usage and leftovers, 3 dependencies and change impact, 4 correctness and maintainability, 5 imports, exports and processes, 6 how far to trust the analysis", 0), number=("string", "one test by its number, such as 1.7", 0))},
            {"name": "propose_action", "description": "Keep a suggestion on the Action plan as your proposal, apart from the deterministic cards and unconfirmed until the owner takes it on. Only when the owner asks for it to be kept.", "input_schema": S(title=("string", "action-led, names the object"), why=("string", "the evidence and the supportable value, one or two sentences"), steps=("string", "the steps, one per line"), done_when=("string", "how the owner will know it worked"), model=("string", "model name"), objects=("string", "comma-separated: 'Module.Line Item' or module names in that model, all real"))},
            {"name": "set_action_state", "description": "Record the owner's decision, with their reason, on an action of the plan (its key from action_plan, or proposal:<id>) or on an over-dimensioned line item (its key from size, size:<model>::<Module.Line Item>). Only when the owner says so.", "input_schema": S(key=("string", "the action's key from action_plan, proposal:<id>, or a size row's key"), state=("string", "to_review | investigating | done | keep_current_design"), reason=("string", "the owner's why"))},
            {"name": "size", "description": "Why a model is the size it is: list, time-range and version sizes solved from cell counts (each with how many line items agree; never exported), what each axis costs in cells, and the over-dimensioned line items (an axis their formula never varies over) priced in cells saved, plus the modules ranked by exact cell count with their share of the model (quote those, not rounded totals). With a line item name: that item's applied versus required axes. Call when the owner asks about size, cells, Versions, Time, dimensions or headroom.", "input_schema": S(model=("string", "model name (default: the largest)", 0), name=("string", "'Module.Line Item' to judge one line item", 0))},
            {"name": "query_line_items", "description": "Count and filter line items across every model of the workspace, exactly, from the line-item index: by a function the formula uses (FINDITEM, IF, SUM, LOOKUP, DIVIDE ...), by what it references or what references it, by a dimension it applies to, by format, module, model, text in its name, formula or notes, calculated or input, unreferenced, minimum cells, formula length or number of IFs. Returns the exact count, the cells those line items hold, the count by model, an optional breakdown (group_by) and the first rows by sort. Call for any question of the form how many, which, list or count line items: never count from memory or from a truncated list.", "input_schema": S(model=("string", "one model", 0), module=("string", "one module", 0), function=("string", "a function, clause or IF the formula uses", 0), references=("string", "a module or 'Module.Line Item' the formula reads", 0), referenced_by=("string", "a module or 'Module.Line Item' whose formulas read it", 0), dimension=("string", "a list, Time or Versions it applies to", 0), format=("string", "NUMBER | BOOLEAN | TEXT | DATE | LIST | TIME_ENTITY | NONE", 0), text=("string", "words in the name, formula or notes", 0), calculated=("boolean", "true: has a formula; false: an input", 0), unreferenced=("boolean", "true: nothing reads it", 0), min_cells=("integer", "at least this many cells", 0), min_formula_length=("integer", "formula at least this many characters", 0), min_ifs=("integer", "at least this many IFs", 0), summary=("string", "summary method contains", 0), group_by=("string", "model | module | format | function | dimension | summary", 0), sort=("string", "cells (default) | effort | formula_length | used_by | uses | ifs | depth | name", 0), limit=("integer", "rows to return, at most 25, default 10", 0))},
            {"name": "build_plan", "description": "Check a build you propose against one model and turn it into instructions a builder follows. Call when the owner asks for a plan to build something. "
             "Give every module you would add or extend with its line items: name, format, summary method, and formula in Anaplan syntax (blank for an input), a reference to another module written as 'Module Name'.Line Item. "
             "If the build replaces something the model does today, list under changes each existing line item whose formula must switch over to what you built, with its whole new formula; change nothing else. "
             "Give checks_after: what the builder compares or looks at once it is built to know it is right, six at most. Under lists, name each list or line item subset the build needs that the model does not have, and say what it is. "
             "Code parses every formula, resolves every reference against the model and against the plan's own new objects, sorts everything so nothing is built before what it refers to, and rejects the plan (with what to fix) "
             "if a formula does not parse, a reference resolves to nothing, or there is a cycle. Look up the existing modules and line items you intend to read or change first; reuse what exists.",
             "input_schema": {"type": "object", "required": ["model", "title", "modules"], "properties": {
                 "model": {"type": "string", "description": "the model the plan is for"},
                 "title": {"type": "string", "description": "what is being built, a few words"},
                 "modules": {"type": "array", "description": "the modules to add or extend, in any order", "items": {"type": "object", "required": ["name", "line_items"], "properties": {
                     "name": {"type": "string", "description": "module name; an existing module's exact name to add line items to it"},
                     "applies_to": {"type": "array", "items": {"type": "string"}, "description": "the lists the module applies to, and Time or Versions if it has them"},
                     "note": {"type": "string", "description": "one plain line: what the module is for"},
                     "line_items": {"type": "array", "items": {"type": "object", "required": ["name"], "properties": {
                         "name": {"type": "string"}, "format": {"type": "string", "description": "Number | Boolean | Text | Date | List | Time period | No data"},
                         "summary": {"type": "string", "description": "None | Sum | Formula | Average | Min | Max ..."},
                         "formula": {"type": "string", "description": "Anaplan formula; blank for an input"},
                         "note": {"type": "string", "description": "optional: why this line item"}}}}}}},
                 "changes": {"type": "array", "description": "existing line items whose formula is replaced so the model uses what the plan builds (the switch-over); leave empty if nothing existing changes",
                             "items": {"type": "object", "required": ["module", "line_item", "formula"], "properties": {
                                 "module": {"type": "string", "description": "the existing module's exact name"}, "line_item": {"type": "string", "description": "the existing line item's exact name"},
                                 "formula": {"type": "string", "description": "its whole new formula"}, "note": {"type": "string", "description": "one plain line: what changes for the reader of this line item"}}}},
                 "lists": {"type": "array", "description": "each list or line item subset the plan needs that the model does not have yet", "items": {"type": "object", "required": ["name", "what"], "properties": {
                     "name": {"type": "string"}, "what": {"type": "string", "description": "one plain line: what it is (a list, or a line item subset of which module) and what it holds"}}}},
                 "checks_after": {"type": "array", "items": {"type": "string"}, "description": "what to check once it is built, each one plain sentence a builder can act on; put an object name in backticks only if it is the exact name"}}}},
            {"name": "search_documents", "description": "Search the workspace's project documents (design records, meeting notes, handover notes, change requests, scripts) by keyword and by the objects a section names. Returns section hits with ids and snippets, never whole documents. Call for any question about why something was built, decided or left as it is.", "input_schema": S(query=("string", "keywords from the question", 0), objects=("string", "comma-separated module or 'Module.Line Item' names the question is about", 0), document=("string", "restrict to one document id", 0), limit=("integer", "max hits, default 6", 0))},
            {"name": "get_section", "description": "Read one section of a project document in full, by the section id search_documents returned. Read a section before quoting it or resting an answer on it.", "input_schema": S(section=("string", "a section id such as s-1a2b3c4d5e"))},
        ]
