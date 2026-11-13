"""The demo state (v0.2 P4): two fictional workspaces written from the files in examples/caldergate, the same every
time. "Caldergate Distribution Group" is four models with their project documents, owner notes and one retired feed;
"Caldergate Stores" is one model of several thousand line items. Resetting replaces any earlier copy and nothing else:
other workspaces are never touched.

The files ship with the package (examples/ beside the source in a checkout, anaplan_architect/examples in an install).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

KINDS = (("Line Items.csv", "line_items"), ("Actions.csv", "actions"), ("Modules.csv", "modules"))


def root() -> Path | None:
    here = Path(__file__).resolve()
    for cand in (here.parents[1] / "examples" / "caldergate", here.parents[3] / "examples" / "caldergate"):
        if (cand / "demo.json").is_file():
            return cand
    return None


def manifest() -> dict:
    r = root()
    if r is None:
        raise FileNotFoundError("the demo files (examples/caldergate) are not installed with this copy")
    m = json.loads((r / "demo.json").read_text(encoding="utf-8"))
    m["root"] = str(r)
    return m


def ids() -> list[str]:
    try:
        return [w["id"] for w in manifest()["workspaces"]]
    except FileNotFoundError:
        return []


def estate_id(key: str, user_id: str | None) -> str:
    """The id of a demo workspace: the key itself on a server with no accounts, the key and the login otherwise."""
    return key if not user_id else f"{key}-{user_id[2:] if user_id.startswith('u-') else user_id}"


def doc_id(eid: str, filename: str) -> str:
    return "d-" + hashlib.sha1(f"{eid}\x1f{filename}".encode()).hexdigest()[:10]


def files_of(ws: dict) -> list[tuple[str, str, bytes, str]]:
    """(model name, kind, bytes, original name) for every export of a demo workspace."""
    r = Path(manifest()["root"])
    out = []
    for m in ws["models"]:
        for fname, kind in KINDS:
            p = r / m["folder"] / fname
            if p.is_file():
                out.append((m["name"], kind, p.read_bytes(), fname))
    return out
