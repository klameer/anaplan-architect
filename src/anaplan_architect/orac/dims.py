"""Size: dimension inference and cell cost (Orac backlog 18), over anaplan-estate's engine.

The engine is `anaplan_estate.dims`, the same code behind test 1.7 of the free report (line items with a
dimension their formula does not use): sizes solved from cell counts, the axes each formula requires, and
the price of an axis it does not. It began here and moved there, so the report and this page cannot give two
different answers for one line item. What stays here is what the engine does not know about: one model of
one snapshot computed once (ModelDims), citation ids, the summary the Size page reads, and the rows the
`size` tool hands the architect with the owner's decisions on them.

The exports never say how big a list is, how many periods a time range holds or how many versions there
are: every size is solved from Cell Count and reported with the number of line items that agree, never as a
fact the export stated. Where a model-level export leaves Applies To blank (the module's dimensions, unnamed
without a Modules export), lists are not compared by name and only Time and Versions are judged. The page says so.
"""
from __future__ import annotations
from collections import Counter
from anaplan_estate.dims import (TIME, VERSIONS, Judge, bundle, bundle_module, factor_label, factor_of, factors,          # noqa: F401  (re-exported:
                                 has_time, has_versions, infer_sizes, is_bundle, list_axes, module_dims, price)          # the names this module had)
from .evidence import Evidence


class ModelDims:
    """Everything the Size page and the `size` tool read for one model of one snapshot: computed once, kept by the caller."""

    def __init__(self, m, snapshot_id: str | None = None):
        self.m = m
        self.snapshot_id = snapshot_id or ""
        self.sizes = infer_sizes(m.model)
        self.judge = Judge(m.model, m.graph, self.sizes)
        self.items: dict[str, dict] = {}
        for li in m.model.line_items.values():
            if li.is_header:
                continue
            j = self.judge.judge(li)
            price(j, li, self.sizes)
            self.items[j["ref"]] = j
        self._ev = Evidence("", self.snapshot_id)

    def _size_of(self, axis: str, li) -> int | None:
        s = self.sizes.get(factor_of(axis, li))
        return s["size"] if s else None

    def cite(self, ref: str) -> str:
        return self._ev.mint("line_item", self.m.name, ref).id

    def item(self, ref: str) -> dict | None:
        j = self.items.get(ref) or next((v for k, v in self.items.items() if k.lower() == ref.lower()), None)
        if j is None:
            return None
        li = self.m.model.line_items[(j["module"], j["name"])]
        out = dict(j, id=self.cite(j["ref"]), model=self.m.name, snapshot=self.snapshot_id)
        out["axis_sizes"] = {a: self._size_of(a, li) for a in j["applied"]}
        return out

    def axes(self) -> list[dict]:
        """What each axis costs: the items that carry it, their cells, and the cells it multiplies in (cells minus what
        they would be without it) where its size is known."""
        by: dict[str, dict] = {}
        for li in self.m.model.line_items.values():
            if li.is_header or not li.cell_count:
                continue
            for a in self.judge.axes_of(li):
                d = by.setdefault(a, {"axis": a, "items": 0, "cells": 0, "marginal": 0, "unpriced_items": 0, "sizes": Counter()})
                d["items"] += 1
                d["cells"] += li.cell_count
                s = self._size_of(a, li)
                if s:
                    d["marginal"] += li.cell_count - li.cell_count // s
                    d["sizes"][s] += 1
                else:
                    d["unpriced_items"] += 1
        out = []
        for a, d in by.items():
            sizes = d.pop("sizes")
            d["size"] = sizes.most_common(1)[0][0] if sizes else None
            d["size_note"] = ("varies by scale and range: " + ", ".join(str(k) for k, _ in sizes.most_common(4))) if a == TIME and len(sizes) > 1 else ""
            d["kind"] = "time" if a == TIME else "versions" if a == VERSIONS else "module" if is_bundle(a) else "list"
            out.append(d)
        out.sort(key=lambda d: (-d["marginal"], -d["cells"]))
        return out

    def summary(self, limit: int = 300) -> dict:
        m = self.m
        lis = [li for li in m.model.line_items.values() if not li.is_header]
        total = sum(li.cell_count for li in lis)
        has_cells = m.model.has("Cell Count")
        over = [j for j in self.items.values() if j["judged"] and j["extra"]]
        over.sort(key=lambda j: (-(j["saved_cells"] or 0), -j["cells"]))
        not_judged = Counter(j["reason"].split(":")[0] for j in self.items.values() if not j["judged"] and j["reason"] and not j["reason"].startswith("input"))
        inputs = sum(1 for j in self.items.values() if j["reason"].startswith("input"))
        sizes = []
        for f, s in self.sizes.items():
            if isinstance(f, tuple):
                sizes.append({"factor": factor_label(f), "kind": f[0], "size": s["size"], "evidence": s["evidence"], "agreement": s["agreement"], "items": s["items"],
                              "assumed": s.get("assumed", False)})
        order = {"dim": 0, "mod": 1, "time": 2, "versions": 3}
        sizes.sort(key=lambda s: (order.get(s["kind"], 9), -s["items"]))
        priced = [j for j in over if j["saved_cells"] is not None]
        rows = [dict(j, id=self.cite(j["ref"]), formula=j["formula"][:160]) for j in over[:limit]]
        coverage = []
        if not has_cells:
            coverage.append("No Cell Count column in this export: sizes cannot be inferred and nothing is priced; the axis judgement still stands.")
        ex = self.sizes["_explained"]
        if ex["of"]:
            coverage.append(f"Sizes are inferred from cell counts, never exported: the sizes found reproduce {ex['items']} of {ex['of']} cell counts exactly"
                            + (f" ({ex['share'] * 100:.0f}%)" if ex["share"] is not None else "") + ".")
        blank, bundled = self.sizes["_blank"], self.sizes["_bundled_modules"]
        if bundled:
            coverage.append(f"Applies To is blank on {blank} of {len(lis)} line items: they take their module's dimensions. Without a Modules export those are "
                            f"unnamed, so {len(bundled)} module(s) carry their dimensions as one sized factor; on their line items only Time and Versions are judged.")
        elif blank and not m.model.has_modules_export:
            coverage.append(f"Applies To is blank on {blank} line item(s); their cell counts say they carry no dimension, so they are judged in full.")
        if self.sizes["_unknown"]:
            coverage.append(f"{len(self.sizes['_unknown'])} factor(s) could not be sized (no line item isolates them): "
                            + ", ".join(factor_label(f) for f in self.sizes["_unknown"][:8]) + ("…" if len(self.sizes["_unknown"]) > 8 else ""))
        assumed = self.sizes.get("_assumed") or []
        if assumed:
            mods = [f for f in assumed if f[0] == "mod"]
            rest = [f for f in assumed if f[0] != "mod"]
            coverage.append(f"{len(mods)} module(s) with a blank Applies To that nothing isolates are taken to carry no dimension"
                            + (f"; {len(rest)} size(s) follow from that assumption and are marked assumed: " + ", ".join(factor_label(f) for f in rest[:6]) if rest else "") + ".")
        sums = sum(1 for j in self.items.values() if j["sums"])
        if sums:
            coverage.append(f"{sums} formula(s) aggregate with SUM or its kin to a list the export does not name: on those, the list the aggregation targets is taken as required.")
        by_mod: dict[str, list] = {}
        for li in lis:
            by_mod.setdefault(li.module, []).append(li)
        modules = sorted(({"module": name, "cells": sum(x.cell_count for x in xs), "line_items": len(xs)} for name, xs in by_mod.items()),
                         key=lambda r: (-r["cells"], r["module"]))
        for r in modules:
            r["share"] = round(r["cells"] / total * 100, 1) if total else None
        return {"model": m.name, "model_id": self._ev.mint("model", m.name, m.name).id, "snapshot": self.snapshot_id, "cells": total, "has_cells": has_cells,
                "modules": modules,
                "line_items": len(lis), "calculated": sum(1 for j in self.items.values() if not j["reason"].startswith("input")), "inputs": inputs,
                "explained": ex, "sizes": sizes, "axes": self.axes(),
                "over": rows, "over_summary": {"items": len(over), "cells": sum(j["cells"] for j in over), "saved": sum(j["saved_cells"] for j in priced),
                                                "priced": len(priced), "unpriced": len(over) - len(priced), "partial": sum(1 for j in over if j["partial"]),
                                                "constant": sum(1 for j in over if j["constant"]),
                                                "lists_unjudged": sum(1 for j in self.items.values() if j["judged"] and not j["lists_judged"])},
                "not_judged": dict(not_judged), "shown": len(rows),
                "coverage": coverage,
                "limits": ["An over-dimensioned line item repeats one value along an axis it applies to; the cells it saves are the cells it would not have without that axis. Whether the repetition is wanted (a rate shown per segment on a view) is the owner's call: mark it and give the reason.",
                           "An axis the references carry that the item lacks is aggregated or mapped by Anaplan implicitly (hierarchy, subset, summary); the exports do not carry those relations, so it is listed, not judged.",
                           "Cell counts are read as the export gives them; whether they include summary cells depends on the model, and the inferred sizes carry that convention with them."]}


def summarize_for_tool(md: ModelDims, cite_li, cite_model, limit: int = 25, states: dict | None = None, cite_module=None) -> dict:
    """The `size` tool's answer for one model: what the page shows, cut to what a conversation needs, every object cited. A row
    the owner has decided on (keep current design, done) is kept apart under `decided` with the reason, so it is not raised again.
    The modules come ranked by exact cell count, so a handover quotes figures a tool handed rather than totals it added up."""
    from .findings_state import size_key
    s = md.summary(limit=limit)
    cite_model(s["model"])
    for row in s["over"]:
        cite_li(row["module"], row["name"])
    keep = ("ref", "cells", "applied", "required", "extra", "implicit", "saved_cells", "price_assumed", "unpriced", "partial", "constant", "lists_judged", "reason")
    st = states or {}
    rows, decided = [], []
    for r in s["over"]:
        key = size_key(s["model"], r["ref"]); d = st.get(key)
        if d and d["state"] in ("keep_current_design", "done"):
            decided.append({"ref": r["ref"], "key": key, "state": d["state"], "reason": d["reason"], "by": d.get("by"), "when": d.get("updated"), "saved_cells": r["saved_cells"]})
            continue
        row = {k: r[k] for k in keep} | {"key": key}
        if d:
            row["decision"] = {"state": d["state"], "reason": d["reason"]}
        rows.append(row)
    mods = [dict(r, module=(cite_module(r["module"]) if cite_module else r["module"])) for r in s["modules"][:20]]
    return {"model": s["model"], "cells": s["cells"], "line_items": s["line_items"], "calculated": s["calculated"], "explained": s["explained"],
            "modules": mods, "modules_shown": f"{len(mods)} of {len(s['modules'])}, largest first",
            "sizes": s["sizes"][:40], "axes": [{k: v for k, v in a.items() if k != "unpriced_items"} for a in s["axes"][:20]],
            "over_dimensioned": rows, "decided": decided, "over_summary": s["over_summary"] | {"decided": len(decided)}, "not_judged": s["not_judged"],
            "coverage": s["coverage"], "limits": s["limits"],
            "note": "a row under decided carries the owner's decision and reason: do not raise it again unless the owner asks; a decision on any row is recorded with set_action_state and the row's key"}
