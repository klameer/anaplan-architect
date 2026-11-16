"""How a line item is calculated, as the page draws it: the formula the grammar parsed, taken apart into labelled parts
with every reference resolved to the object it names, and the upstream trace back to the inputs.

Everything here is read off the parse tree and the formula graph. Nothing is the model's own words, so the picture is
right even when the prose beside it is thin.
"""
from __future__ import annotations
from anaplan_grammar.parser import parse, ParseError
from anaplan_grammar.unparse import unparse

TRACE_DEPTH = 4
TRACE_NODES = 36


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, (list, tuple)):
        for x in node:
            yield from _walk(x)


def _bare(text: str) -> str:
    """Without one pair of brackets that wraps the whole part: the grammar writes them back for safety, a reader does not need them."""
    t = text.strip()
    while t.startswith("(") and t.endswith(")"):
        depth = 0
        for i, ch in enumerate(t):
            depth += ch == "("
            depth -= ch == ")"
            if depth == 0 and i < len(t) - 1:
                return t
        t = t[1:-1].strip()
    return t


def _segments(node, targets: dict[tuple, str]) -> list[dict]:
    """One part of a formula as the page shows it: plain text, each function name, and each reference as the object it
    resolves to (`Module.Line Item`), or as written when it names a list, a member or nothing the model has."""
    text = _bare(unparse(node))
    marks: list[tuple[str, str, str]] = []                # (as written, kind, value)
    for n in _walk(node):
        if n.get("t") == "ref":
            path = tuple(n.get("path") or ())
            marks.append((unparse(n), "ref" if path in targets else "name", targets.get(path) or ".".join(path)))
        elif n.get("t") == "call" and n.get("f"):
            marks.append((str(n["f"]), "fn", str(n["f"])))
    marks = sorted({m for m in marks if m[0]}, key=lambda m: -len(m[0]))
    out: list[dict] = []
    i = 0
    while i < len(text):
        hit = None
        for written, kind, value in marks:
            if text.startswith(written, i):
                if kind == "fn" and not text.startswith("(", i + len(written)):      # a function name is only one where it is called
                    continue
                if kind == "fn" and i and (text[i - 1].isalnum() or text[i - 1] == "_"):
                    continue
                hit = (written, kind, value); break
        if hit:
            out.append({"t": hit[1], "v": hit[2]}); i += len(hit[0])
        else:
            if out and out[-1]["t"] == "text":
                out[-1]["v"] += text[i]
            else:
                out.append({"t": "text", "v": text[i]})
            i += 1
    return out


def parts(tree, targets: dict[tuple, str]) -> dict:
    """An IF chain as its branches in order, each with its condition and its result, and what is left when none holds.
    Anything else as one expression, with the function it turns on."""
    if isinstance(tree, dict) and tree.get("t") == "if":
        branches, node = [], tree
        while isinstance(node, dict) and node.get("t") == "if":
            branches.append({"label": "IF" if not branches else "ELSE IF", "when": _segments(node["c"], targets), "then": _segments(node["a"], targets)})
            node = node.get("b")
        return {"shape": "if", "branches": branches, "otherwise": _segments(node, targets) if node is not None else []}
    top = tree.get("f") if isinstance(tree, dict) and tree.get("t") == "call" else None
    return {"shape": "expression", "function": top, "text": _segments(tree, targets)}


def block(w, name: str, model: str | None = None) -> dict | None:
    """The calculation of one line item, or None when the workspace has no such line item."""
    kind, m, obj = w.find_object(name, model)
    if kind != "line_item":
        return None
    g, key = m.graph, obj.key
    ref = f"{key[0]}.{key[1]}"
    li = m.model.line_items
    is_input = lambda k: not (li[k].formula or "").strip()
    out = {"type": "calculation", "model": m.name, "ref": ref, "module": key[0], "name": key[1], "formula": obj.formula or "", "format": obj.format_type,
           "applies_to": list(obj.applies_to), "cells": obj.cell_count, "summary": obj.summary}
    targets = {tuple(r.path): f"{r.target[0]}.{r.target[1]}" for r in g.refs.get(key, []) if r.target}
    if not (obj.formula or "").strip():
        out |= {"parts": {"shape": "input"}, "functions": [], "references": []}
    else:
        try:
            tree = parse(obj.formula)
            out["parts"] = parts(tree, targets)
            out["functions"] = sorted({str(n["f"]) for n in _walk(tree) if n.get("t") == "call" and n.get("f")})
        except ParseError as e:
            out |= {"parts": {"shape": "unparsed", "error": str(e)[:200]}, "functions": []}
        out["references"] = [{"ref": f"{t[0]}.{t[1]}", "input": is_input(t)} for t in sorted(g.edges.get(key, ()))]
    # the upstream trace: every line item it rests on, at its shortest distance, back to the inputs
    lin = {**g.lineage(key, TRACE_DEPTH), key: 0}
    order = sorted(lin.items(), key=lambda kv: (kv[1], kv[0]))
    full = {**g.lineage(key, None), key: 0}
    kept = [k for k, _ in order][:TRACE_NODES]
    keep = set(kept)
    out["trace"] = {
        "nodes": [{"ref": f"{k[0]}.{k[1]}", "distance": lin[k], "input": is_input(k), "module": k[0], "name": k[1]} for k in kept],
        "edges": sorted([f"{a[0]}.{a[1]}", f"{b[0]}.{b[1]}"] for a in kept for b in g.edges.get(a, ()) if b in keep and lin[b] == lin[a] + 1),
        "upstream": len(full) - 1, "inputs": sum(1 for k in full if k != key and is_input(k)),
        "depth": max(full.values()) if full else 0, "truncated": len(full) > len(kept)}
    return out
