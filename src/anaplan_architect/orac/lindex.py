"""The line-item index (v0.2 P2): every line item of a snapshot as a row in SQLite, with the references the grammar
found and the functions each formula uses. The parse held in memory still answers impact, lineage and explain; this
answers counting and filtering ("how many line items use FINDITEM", "which line items read SYS05 FX Rates and apply to
Versions") across every model, exactly, and returns counts and the first rows, never the list.

Built once per snapshot, the first time it is asked for, from the same parse the engine uses: its figures are the
engine's figures. FTS5 over names, formulas and notes; no embeddings.
"""
from __future__ import annotations
import re
from .db import Db

MAX_ROWS = 25
SORTS = {"cells": "i.cells DESC", "effort": "COALESCE(i.effort,0) DESC", "formula_length": "i.formula_len DESC", "used_by": "i.used_by DESC",
         "uses": "i.uses DESC", "ifs": "i.ifs DESC", "depth": "i.depth DESC", "name": "i.ref ASC"}
GROUPS = ("model", "module", "format", "function", "dimension", "summary")


def _walk(node, fn: str, funcs: dict, refs: list, depth: int = 1) -> int:
    """Functions, clauses and IFs of a parsed formula, each reference with the function it sits in, and the nesting depth."""
    if isinstance(node, list):
        return max([_walk(x, fn, funcs, refs, depth) for x in node] or [depth])
    if not isinstance(node, dict):
        return depth
    t = node.get("t")
    here = fn
    deepest = depth
    if t == "call":
        here = str(node.get("f", "")).upper()
        funcs[(here, "function")] = funcs.get((here, "function"), 0) + 1
    elif t == "if":
        here = "IF"
        funcs[("IF", "keyword")] = funcs.get(("IF", "keyword"), 0) + 1
    elif t == "ref":
        refs.append((tuple(node.get("path") or ()), fn))
        return depth
    if t == "clause":
        deepest = max(deepest, _walk(node.get("x"), fn, funcs, refs, depth + 1))
        for c in node.get("clauses") or []:
            k = str(c.get("k", "")).upper()
            funcs[(k, "clause")] = funcs.get((k, "clause"), 0) + 1
            deepest = max(deepest, _walk(c.get("m"), k, funcs, refs, depth + 1))
        return deepest
    for key, v in node.items():
        if key in ("t", "f", "op", "k") or not isinstance(v, (dict, list)):
            continue
        deepest = max(deepest, _walk(v, here, funcs, refs, depth + (1 if t in ("call", "if") else 0)))
    return deepest


def _format(li) -> str:
    return (getattr(li, "format_type", "") or "").upper() or "NONE"


def has(db: Db, sid: str) -> bool:
    return db.one("SELECT 1 FROM li_index WHERE snapshot_id=? LIMIT 1", sid) is not None


def build(db: Db, sid: str, estate_run) -> dict:
    """(Re)write the index of a snapshot from its parse. One transaction; idempotent."""
    from anaplan_grammar.parser import parse
    n_items = n_refs = 0
    with db.tx():
        for t in ("li_funcs", "li_refs", "li_index"):
            db.run(f"DELETE FROM {t} WHERE snapshot_id=?", sid)
        for m in estate_run.models:
            g = m.graph
            for key, li in m.model.line_items.items():
                if getattr(li, "is_header", False):
                    continue
                mod = m.model.modules.get(li.module)
                dims = list(li.applies_to) or (list(mod.applies_to) if mod else [])
                ref = f"{key[0]}.{key[1]}"
                funcs: dict = {}; found: list = []
                depth = 0; parsed = 1
                if li.formula:
                    if key in g.parse_errors:
                        parsed = 0
                    else:
                        try:
                            depth = _walk(parse(li.formula), "", funcs, found)
                        except Exception:
                            parsed = 0
                db.run("INSERT OR REPLACE INTO li_index(snapshot_id, model, module, name, ref, format, applies_to, time_scale, versions, summary, formula, notes, cells, effort, "
                       "calculated, parsed, formula_len, ifs, depth, uses, used_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       sid, m.name, key[0], key[1], ref, _format(li), "|" + "|".join(dims) + "|" if dims else "", li.time_scale or "", li.versions or "", li.summary or "",
                       li.formula or "", li.notes or "", int(li.cell_count or 0), li.calc_effort, 1 if li.formula else 0, parsed, len(li.formula or ""),
                       funcs.get(("IF", "keyword"), 0), depth, len(g.edges.get(key, ())), len(g.rev.get(key, ())))
                n_items += 1
                where: dict = {}                       # every function or clause a reference sits in, not only the first
                for path, fn in found:
                    where.setdefault(path, set()).add(fn)
                seen = set()
                for r in g.refs.get(key, []):
                    if r.target is None or r.target in seen:
                        continue
                    seen.add(r.target)
                    db.run("INSERT INTO li_refs(snapshot_id, model, from_ref, to_ref, to_module, fn) VALUES (?,?,?,?,?,?)", sid, m.name, ref,
                           f"{r.target[0]}.{r.target[1]}", r.target[0], "|".join(sorted(x for x in where.get(tuple(r.path), ()) if x)))
                    n_refs += 1
                for (fn, kind), n in funcs.items():
                    db.run("INSERT OR REPLACE INTO li_funcs(snapshot_id, model, ref, fn, kind, n) VALUES (?,?,?,?,?,?)", sid, m.name, ref, fn, kind, n)
    return {"line_items": n_items, "references": n_refs}


def drop(db: Db, sid: str) -> None:
    """Forget a snapshot's index: after a model is renamed or the snapshot is parsed again, the next read writes it afresh."""
    with db.tx():
        for t in ("li_funcs", "li_refs", "li_index"):
            db.run(f"DELETE FROM {t} WHERE snapshot_id=?", sid)


def _shape(estate_run) -> dict:
    return {m.name: sum(1 for li in m.model.line_items.values() if not getattr(li, "is_header", False)) for m in estate_run.models}


def ensure(db: Db, sid: str, estate_run) -> None:
    """Write the index if it is not there, or if it no longer matches the parse it is read beside: the same models by
    name with the same number of line items each. A rename, a model added or retired, or rows lost all rebuild it."""
    have = {r["model"]: r["n"] for r in db.q("SELECT model, COUNT(*) AS n FROM li_index WHERE snapshot_id=? GROUP BY model", sid)}
    if have != {k: v for k, v in _shape(estate_run).items() if v}:
        build(db, sid, estate_run)


def _like(s: str) -> str:
    """A name as a LIKE operand: its own % and _ are those characters, not wildcards (used with ESCAPE '\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts(text: str) -> str:
    terms = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_%?]*", text or "") if len(w) >= 2][:12]
    return " AND ".join('"' + t + '"' for t in terms)


def query(db: Db, sid: str, model: str | None = None, module: str | None = None, function: str | None = None, references: str | None = None,
          referenced_by: str | None = None, dimension: str | None = None, format: str | None = None, text: str | None = None, calculated: bool | None = None,
          unreferenced: bool | None = None, min_cells: int | None = None, min_formula_length: int | None = None, min_ifs: int | None = None,
          summary: str | None = None, group_by: str | None = None, sort: str = "cells", limit: int = 10) -> dict:
    """Count and list line items by what they are and what their formulas do. Every filter narrows; the answer is the
    exact count, the cells those line items hold, the count by model, an optional breakdown, and the first rows by `sort`."""
    where, args = ["i.snapshot_id=?"], [sid]

    def add(sql, *a):
        where.append(sql); args.extend(a)
    if model:
        add("lower(i.model)=lower(?)", model)
    if module:
        add("lower(i.module)=lower(?)", module)
    if format:
        add("i.format LIKE ? ESCAPE '\\'", "%" + _like(format.strip().upper()) + "%")
    if summary:
        add("lower(i.summary) LIKE ? ESCAPE '\\'", "%" + _like(summary.strip().lower()) + "%")
    if dimension:
        add("lower(i.applies_to) LIKE ? ESCAPE '\\'", "%|" + _like(dimension.strip().lower()) + "|%")
    if calculated is not None:
        add("i.calculated=?", 1 if calculated else 0)
    if unreferenced is not None:
        add("i.used_by=0" if unreferenced else "i.used_by>0")
    if min_cells is not None:
        add("i.cells>=?", int(min_cells))
    if min_formula_length is not None:
        add("i.formula_len>=?", int(min_formula_length))
    if min_ifs is not None:
        add("i.ifs>=?", int(min_ifs))
    if function:
        add("EXISTS (SELECT 1 FROM li_funcs f WHERE f.snapshot_id=i.snapshot_id AND f.model=i.model AND f.ref=i.ref AND f.fn=?)", function.strip().upper().rstrip("(").rstrip(":"))
    if references:
        r = references.strip().strip("'")
        add("EXISTS (SELECT 1 FROM li_refs r WHERE r.snapshot_id=i.snapshot_id AND r.model=i.model AND r.from_ref=i.ref AND (lower(r.to_ref)=lower(?) OR lower(r.to_module)=lower(?)))", r, r)
    if referenced_by:
        r = referenced_by.strip().strip("'")
        add("EXISTS (SELECT 1 FROM li_refs r WHERE r.snapshot_id=i.snapshot_id AND r.model=i.model AND r.to_ref=i.ref AND (lower(r.from_ref)=lower(?) OR lower(r.from_ref) LIKE lower(?) ESCAPE '\\'))", r, _like(r) + ".%")
    if text and _fts(text):
        add("i.rowid IN (SELECT rowid FROM li_fts WHERE li_fts MATCH ?)", _fts(text))
    w = " AND ".join(where)
    tot = db.one(f"SELECT COUNT(*) AS n, COALESCE(SUM(i.cells),0) AS cells, COALESCE(SUM(i.effort),0) AS effort FROM li_index i WHERE {w}", *args)
    out = {"count": tot["n"], "cells": tot["cells"],
           "of_line_items": db.one("SELECT COUNT(*) AS n FROM li_index WHERE snapshot_id=?", sid)["n"],
           "by_model": {r["model"]: r["n"] for r in db.q(f"SELECT i.model, COUNT(*) AS n FROM li_index i WHERE {w} GROUP BY i.model ORDER BY n DESC", *args)}}
    if group_by:
        g = group_by.strip().lower()
        if g not in GROUPS:
            return {"error": f"group_by must be one of {', '.join(GROUPS)}"}
        if g == "function":
            # a line item once per function, however many times or in how many ways (call, clause, keyword) the function appears in it
            rows = db.q(f"SELECT key, COUNT(*) AS n, COALESCE(SUM(cells),0) AS cells FROM (SELECT DISTINCT f.fn AS key, i.model, i.ref, i.cells FROM li_index i JOIN li_funcs f "
                        f"ON f.snapshot_id=i.snapshot_id AND f.model=i.model AND f.ref=i.ref WHERE {w}) GROUP BY key ORDER BY n DESC, key LIMIT 40", *args)
        elif g == "dimension":
            counts: dict = {}
            for r in db.q(f"SELECT i.applies_to, i.cells FROM li_index i WHERE {w}", *args):
                for d in [x for x in r["applies_to"].split("|") if x]:
                    c = counts.setdefault(d, [0, 0]); c[0] += 1; c[1] += r["cells"]
            rows = [{"key": k, "n": v[0], "cells": v[1]} for k, v in sorted(counts.items(), key=lambda kv: -kv[1][0])[:40]]
        else:
            col = {"model": "i.model", "module": "i.model || ' :: ' || i.module", "format": "i.format", "summary": "i.summary"}[g]
            rows = db.q(f"SELECT {col} AS key, COUNT(*) AS n, COALESCE(SUM(i.cells),0) AS cells FROM li_index i WHERE {w} GROUP BY key ORDER BY n DESC, key LIMIT 40", *args)
        out["groups"] = {"by": g, "rows": [{"key": r["key"] or "(none)", "line_items": r["n"], "cells": r["cells"]} for r in rows]}
    order = SORTS.get((sort or "cells").strip().lower())
    if order is None:
        return {"error": f"sort must be one of {', '.join(SORTS)}"}
    lim = max(0, min(int(limit if limit is not None else 10), MAX_ROWS))
    rows = db.q(f"SELECT i.model, i.ref, i.module, i.name, i.format, i.applies_to, i.cells, i.effort, i.formula_len, i.ifs, i.uses, i.used_by, i.formula FROM li_index i "
                f"WHERE {w} ORDER BY {order}, i.model, i.ref LIMIT ?", *args, lim) if lim else []
    out["rows"] = [{"model": r["model"], "object": r["ref"], "module": r["module"], "name": r["name"], "format": r["format"], "applies_to": [x for x in r["applies_to"].split("|") if x],
                    "cells": r["cells"], "effort_pct": r["effort"], "formula_chars": r["formula_len"], "ifs": r["ifs"], "uses": r["uses"], "used_by": r["used_by"],
                    "formula": r["formula"][:160] + ("…" if len(r["formula"]) > 160 else "")} for r in rows]
    out["rows_shown"] = len(rows)
    out["sorted_by"] = (sort or "cells").strip().lower()
    out["note"] = (f"count is exact over the whole workspace as read; rows are the first {len(rows)} by {out['sorted_by']}: narrow the filters or change sort to see others, "
                   "the full list is never returned")
    return out


def stats(db: Db, sid: str) -> dict:
    r = db.one("SELECT COUNT(*) AS line_items, COALESCE(SUM(calculated),0) AS calculated, COALESCE(SUM(uses),0) AS refs, COUNT(DISTINCT model) AS models FROM li_index WHERE snapshot_id=?", sid)
    r["references"] = r.pop("refs")
    r["functions"] = db.one("SELECT COUNT(DISTINCT fn) AS n FROM li_funcs WHERE snapshot_id=?", sid)["n"]
    return r
