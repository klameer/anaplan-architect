"""The parse, as a unit of work that can run in a subprocess.

`work()` reads a materialised snapshot folder through anaplan-estate, pickles
the EstateRun beside it and writes stats and coverage as JSON. Run in a
spawned process it can be terminated (that is what Cancel does) and its
memory goes back to the system when it ends; run inline it is the same code.
"""
from __future__ import annotations
import json, pickle, sys, traceback
from pathlib import Path


def stats_of(m) -> dict:
    f = m.facts
    a = f.get("actions") or {}
    return {"modules": f["modules"], "line_items": f["line_items"], "calculated": f["calculated"], "cells": f["cells"],
            "parse_rate": f["parse_rate"], "parse_errors": f["parse_errors"], "edges": f["edges"], "patterns": f["patterns"],
            "findings": f["findings"], "unreferenced": f["unreferenced"], "cycles": f["cycles"],
            "imports": a.get("imports"), "exports": a.get("exports"), "processes": a.get("processes"), "stale": a.get("stale_count"),
            "latest_run": a.get("latest_run"), "effort_top10_share": f["effort_top10_share"],
            "agreement": f["referenced_by_check"]["agreement"], "has_modules_export": f["has_modules_export"]}


def work(root: str, aliases: dict, names: dict, key: str) -> dict:
    """Parse `root`; write estate.pkl, estate.key and result.json next to it. Returns the result dict.
    On failure writes result.json with an error and re-raises."""
    root_p = Path(root)
    out = root_p / "result.json"
    try:
        from anaplan_estate import fleet
        er = fleet.run(root, aliases=aliases, names=names)
        res = {"ok": True, "stats": {"models": {m.name: stats_of(m) for m in er.models}, "edges": len(er.edges), "duplicates": len(er.duplicates),
                                     "external_sources": len(er.external), "findings": len(er.findings)},
               "coverage": {m.name: m.facts["coverage"] for m in er.models}}
        tmp = root_p / "estate.pkl.part"
        with open(tmp, "wb") as f:
            pickle.dump(er, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(root_p / "estate.pkl")
        (root_p / "estate.key").write_text(key, encoding="utf-8")
        out.write_text(json.dumps(res, default=str, ensure_ascii=False), encoding="utf-8")
        return res
    except BaseException as ex:            # SystemExit included: fleet raises it on a folder it cannot read
        res = {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:2000], "trace": traceback.format_exc()[-4000:]}
        try:
            out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        raise


def load(root: str | Path, key: str):
    """The pickled run, if it was made from exactly these files, names and aliases; else None."""
    root_p = Path(root)
    try:
        if (root_p / "estate.key").read_text(encoding="utf-8") != key:
            return None
        with open(root_p / "estate.pkl", "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _main(argv: list[str]) -> int:
    root, key, spec = argv[0], argv[1], json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    try:
        work(root, spec.get("aliases") or {}, spec.get("names") or {}, key)
        return 0
    except BaseException:
        return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
