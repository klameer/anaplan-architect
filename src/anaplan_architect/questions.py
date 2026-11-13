"""Questions only an architect can answer about this estate, built from the
facts so every one names a real object. Object names are written in backticks,
the one convention the page and the chat share: the renderer styles a model, a
module and a line item differently, wherever they appear. The deterministic report says what
is there; these ask what it means. Each becomes the opening turn of a
conversation when clicked.
"""
from __future__ import annotations
from anaplan_estate.findings import _c
from .store import Workspace


def suggested(w: Workspace, limit: int = 10) -> list[dict]:
    er = w.estate
    ms = er.models
    q: list[dict] = []

    def add(kind, text, why):
        q.append({"kind": kind, "text": text, "why": why})

    big = max(ms, key=lambda m: m.facts["cells"])
    if big.facts["cells_by_module"]:
        mod, cells, share = big.facts["cells_by_module"][0]
        add("design", f"What design decision explains `{mod}` in `{big.name}` being {_c(cells)} cells ({share}% of the model), and what would a smaller design keep?",
            "The largest module usually encodes one choice: a cube, a code join, a summary by every dimension. Only a reviewer can say whether that choice still earns its size.")
    eff = [m for m in ms if m.facts["has_effort"]]
    if eff:
        w_ = max(eff, key=lambda m: m.facts["cells"])
        name, pct, cells, formula = w_.facts["effort_top"][0]
        add("explain", f"Explain what `{name}` does in plain words, why it carries {pct:.1f}% of `{w_.name}`'s calculation effort, and what would move it.",
            "The effort column says which line item is expensive. It does not say why, or whether the cost is the formula, the dimensionality, or the summary.")
    if er.edges:
        e = er.edges[0]
        add("impact", f"`{e['from']}` feeds `{e['to']}` through {e['actions']} imports. If `{e['from']}`'s structure changed, which modules in `{e['to']}` would break first, and which imports are the fragile ones?",
            "Cross-model impact is inferred from action names; a reviewer reads the targets and says where the coupling is tight.")
    for m in ms:
        a = m.facts["actions"]
        if a and a["stale"]:
            n, d = a["stale"][0]
            add("retire", f"In `{m.name}`, {a['stale_count']} imports and exports have not run since the stale window. Starting with `{n}` (last run {d}), which can be retired safely and what depends on their targets?",
                "Stale actions are either dead or manual. The graph shows what their target modules feed; a reviewer decides which.")
            break
    for m in sorted(ms, key=lambda m: -m.facts["unreferenced"]):
        if m.facts["unreferenced"]:
            add("delete", f"`{m.name}` has {m.facts['unreferenced']:,} calculated line items no formula reads. Which whole modules could be deleted, what would the estate lose, and what might be read by pages the exports do not show?",
                "Unreferenced calculation is either waste or an output. Telling them apart needs the DISCO role, the naming, and the actions that export from the module.")
            break
    if er.duplicates:
        d = er.duplicates[0]
        add("refactor", f"`{d['line_item']}` is calculated identically in {', '.join('`' + x + '`' for x in d['models'])}. Should the logic live in one model and be imported, and how would that be built?",
            "Duplicated logic is a maintenance decision. The fix is a design, not a formula edit.")
    hub = max(ms, key=lambda m: (m.facts["hubs"][0][1] if m.facts["hubs"] else 0))
    if hub.facts["hubs"]:
        n, c = hub.facts["hubs"][0]
        add("risk", f"`{n}` in `{hub.name}` has {c} direct dependents. What is the blast radius of changing it, and how would you make that change safely?",
            "A hub is a single point of failure. The reviewer plans the change, the graph prices it.")
    pat = None
    for m in ms:
        for cl in m.clusters:
            if cl.severity in ("critical", "major") and cl.count >= 5:
                pat = (m, cl); break
        if pat:
            break
    if pat:
        m, cl = pat
        add("materiality", f"Pattern {cl.rule} in `{m.name}`: {cl.label}. Does this matter for this model, or is it a deliberate choice? If it matters, what is the one template fix?",
            "A rule firing 96 times is one decision. Whether it is a fault or a choice is judgement.")
    add("build", f"I want to add a new calculation module to `{big.name}`. Walk me through where it sits in the DISCO layout, what it should be dimensioned on, how it should be named here, and give me the first three formulas, validated.",
        "Building in someone else's model means matching its conventions. The architect reads them from the estate.")
    add("handover", f"Write the handover memo for `{big.name}`: what it is for, the five modules to read first, the three decisions that explain its shape, and the traps.",
        "The page a new builder needs on day one, which no export contains.")
    if len(q) < 6:      # thin estate: fill in with the questions any architect would open with
        have = {x["kind"] for x in q}
        for g in GENERIC:
            if g["kind"] not in have:
                q.append(dict(g, text=g["text"].replace("{model}", f"`{big.name}`")))
    return q[:limit]


# For an estate too thin to name objects (one small model, no actions, no effort column): the
# four questions any architect would open with, each still pointing at the largest model.
GENERIC = [
    {"kind": "design", "text": "What are the design decisions that explain how {model} is built, and what does each one cost and buy?",
     "why": "Every model encodes a few choices about dimensions, versions and how data enters and leaves. Naming them is the first day of any review."},
    {"kind": "risk", "text": "Where is {model} most fragile: the most depended-on line items, any circular references, and what a change to them would touch?",
     "why": "A hub is a single point of failure; the graph prices the change, the reviewer plans it."},
    {"kind": "handover", "text": "Write the handover memo for {model}: what it is for, the modules to read first, the decisions that explain its shape, and the traps.",
     "why": "The page a new builder needs on day one, which no export contains."},
    {"kind": "build", "text": "I want to add a new calculation module to {model}. Walk me through where it sits, what it should be dimensioned on, how it should be named here, and give me the first three formulas, validated.",
     "why": "Building in someone else's model means matching its conventions. The architect reads them from the estate."},
]
