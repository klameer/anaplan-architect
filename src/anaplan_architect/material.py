"""What the architect reads. Never the exports: the estate facts, the
graph, the patterns with their statuses, the longest formulas, the
actions, and the memories. Compact enough for one context window on a
300-module estate; every object named exactly as the validator knows it.
"""
from __future__ import annotations
import re
from collections import Counter
from anaplan_estate.findings import _c
from anaplan_estate.report import _n, _observations
from .store import Workspace, pattern_id

_PREFIX = re.compile(r"^([DISCOF])\s+([A-Z][A-Za-z0-9]*?)(\d*[a-z]?)\b")
_CODE = re.compile(r"^(OUT|CAL|INP|SYS|DAT|FIL)([A-Z]*)(\d*[a-z]?)\b")
DISCO = {"D": "Data", "I": "Inputs", "S": "System", "C": "Calculation", "O": "Output", "F": "Filter", "?": "unprefixed"}
_CODE_ROLE = {"OUT": "O", "CAL": "C", "INP": "I", "SYS": "S", "DAT": "D", "FIL": "F"}


def disco_role(module: str) -> str:
    m = _PREFIX.match(module)
    if m:
        return m.group(1)
    m = _CODE.match(module)
    return _CODE_ROLE[m.group(1)] if m else "?"


def model_material(w: Workspace, m, max_patterns: int = 40, max_formulas: int = 15, notes: bool = True) -> list[str]:
    f = m.facts
    out = [f"# Model: {m.name}", "",
           f"{f['modules']} modules, {_n(f['line_items'])} line items ({_n(f['calculated'])} calculated), {_c(f['cells'])} cells, "
           f"{len(f['dimensions'])} dimensions, {_n(f['edges'])} formula references. Parse rate {f['parse_rate']:.1%}. "
           f"Notes on {f['notes_coverage']:.0%} of line items. Referenced By agreement {f['referenced_by_check']['agreement']}.", ""]
    # DISCO shape
    roles = Counter(); cells = Counter()
    for name, mod in m.model.modules.items():
        if mod.line_items:
            r = disco_role(name); roles[r] += 1; cells[r] += sum(m.model.line_items[(name, li)].cell_count for li in mod.line_items if (name, li) in m.model.line_items)
    out += ["## Shape (DISCO role from module names)", "", "| Role | Modules | Cells |", "|---|---|---|"]
    for r in "DISCOF?":
        if roles[r]:
            out.append(f"| {r} {DISCO[r]} | {roles[r]} | {_c(cells[r])} |")
    out += ["", "## Largest modules by cells", ""] + [f"- {n}: {_c(c)} ({p}%)" for n, c, p in f["cells_by_module"][:8]]
    if f["has_effort"]:
        out += ["", f"## Where calculation time goes (top 10 = {f['effort_top10_share']}%)", ""]
        out += [f"- {name}: {eff:.2f}% effort, {_c(cells)} cells, formula `{formula[:110]}`" for name, eff, cells, formula in f["effort_top"][:12]]
    out += ["", "## Most depended-on line items", ""] + [f"- {n}: {c} direct dependents" for n, c in f["hubs"][:8]]
    out += ["", f"## Graph facts", "",
            f"- Calculated but unreferenced: {_n(f['unreferenced'])}", f"- Circular references: {f['cycles']} ({f['cycles_balance']} via time offset, {f['cycles_fault']} without)",
            f"- Pass-through chains: {f['daisy_chains']}"]
    # longest formulas
    lis = sorted((li for li in m.model.line_items.values() if li.formula and not li.is_header), key=lambda li: -len(li.formula))[:max_formulas]
    out += ["", f"## Longest formulas ({len(lis)})", ""]
    for li in lis:
        out.append(f"- {li.module}.{li.name} ({len(li.formula)} chars, {_c(li.cell_count)} cells): `{li.formula[:220]}{'...' if len(li.formula) > 220 else ''}`")
    a = f["actions"]
    if a:
        out += ["", "## Actions", "",
                f"{a['imports']} imports, {a['exports']} exports, {a['processes']} processes; latest run {a['latest_run'] or 'unknown'}.",
                f"- Imports outside any process: {a['orphan_count']}" + (f": {', '.join(a['orphans'][:8])}" if a["orphans"] else ""),
                f"- Stale or never run: {a['stale_count']}" + (f": {', '.join(n for n, _ in a['stale'][:8])}" if a["stale"] else ""),
                "- Slowest: " + ", ".join(f"{n} ({ms // 1000}s)" for n, ms in a["slow"][:5]),
                "- Most imported-into modules: " + ", ".join(f"{t} ({n})" for t, n in a["imports_by_target"][:6]),
                "- Processes: " + ", ".join(f"{p} ({n} steps)" for p, n in a["process_steps"][:8])]
    # patterns with statuses
    out += ["", f"## Patterns ({f['findings']} findings in {f['patterns']} patterns; cite as pattern:<id> or finding:<RULE>)", ""]
    shown = 0
    for c in m.clusters:
        pid = pattern_id(m, c); st = w.status_of(pid)
        if st in ("incorrect", "fixed"):
            continue
        tag = f" [{st}: {w.statuses[pid]['reason'][:80]}]" if st != "open" else ""
        out.append(f"- pattern:{pid} | {c.severity} | {c.count} finding(s) | {c.message[:110]} | e.g. {c.objects[0] if c.objects else ''}{tag}")
        shown += 1
        if shown >= max_patterns:
            out.append(f"- ... {len(m.clusters) - shown} more patterns"); break
    mems = w.memories_for(model=m.name, rules={c.rule for c in m.clusters})
    if mems and not notes:        # the chat is handed the notes that bear on each question; repeating every note under every model is not lean
        own = [mm for mm in mems if mm["scope"] != "estate"]
        if own:
            out += ["", f"({len(own)} owner note{'s' if len(own) != 1 else ''} about this model or its rules are kept; the ones that bear on a question are handed with it.)"]
    elif mems:
        out += ["", "## What the owner has told us about this model", ""] + [f"- ({mm['scope']}) {mm['text']}" for mm in mems]
    return out


def estate_material(w: Workspace, **kw) -> str:
    er = w.estate
    out = ["# Estate", "", f"{len(er.models)} models: " + ", ".join(m.name for m in er.models), "", "## In one page", ""]
    out += [f"{i}. {h}" for i, h in enumerate(_observations(er), 1)]
    if er.edges:
        out += ["", "## How the models connect (read off import action names: inferred unless the owner has confirmed or retired it)", ""]
        for e in er.edges:
            st = w.edge_state(e["from"], e["to"])
            tag = f" [{st['state']} by the owner: {st['reason'][:100]}]" if st else " [inferred]"
            out.append(f"- {e['from']} -> {e['to']}: {e['actions']} import actions into {', '.join(e['targets'][:5])}{tag}")
    if er.external:
        out += ["", "## External sources named in imports", ""] + [f"- {s}: {len(a)} actions" for s, a in sorted(er.external.items(), key=lambda kv: -len(kv[1]))[:15]]
    if er.duplicates:
        out += ["", "## Logic duplicated across models", ""] + [f"- {d['line_item']} in {', '.join(d['models'])} ({d['copies']} copies): `{d['formula'][:100]}`" for d in er.duplicates[:20]]
    if er.shared_dims:
        out += ["", "## Dimensions shared across models", "", ", ".join(f"{d} ({len(ms)})" for d, ms in er.shared_dims[:30])]
    mems = w.memories_for()
    if mems:
        out += ["", "## What the owner has told us about the estate", ""] + [f"- {mm['text']}" for mm in mems]
    for m in er.models:
        out += ["", "---", ""] + model_material(w, m, **kw)
    out += ["", "---", "", "## What the exports do not show", "",
            "Saved views and their filters, UX pages and which line items they read, dashboards, selective access, list members and subsets (so COLLECT() edges are missing), "
            "planning data and therefore whether any number is right, model history and who changed what. Say so rather than guess."]
    return "\n".join(out)
