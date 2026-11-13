"""Bring the pre-Orac data folder into the store. The old layout was

  <data>/estates/<id>/meta.json          name, models, aliases, created
  <data>/estates/<id>/models/<name>/     Line Items.csv, Actions.csv[, Modules.csv]
  <data>/estates/<id>/.architect/        statuses, memories, transcripts (still used as is)

Each such estate becomes an estate row with its id kept (so .architect and the
conversations under it stay attached), one model row per folder, and one
snapshot built from the files, processed and activated. The folder is left in
place; nothing is deleted. Runs once per estate: an id already in the store is
skipped.
"""
from __future__ import annotations
import datetime, json
from pathlib import Path
from .db import Db
from .blobs import BlobStore
from .snapshots import Snapshots, KINDS, FILE_NAMES
from . import estates as reg


def import_legacy(db: Db, blobs: BlobStore, snaps: Snapshots, data_root: str | Path, workspace_id: str) -> list[dict]:
    data = Path(data_root)
    done = []
    root = data / "estates"
    if not root.is_dir():
        return done
    for d in sorted(root.iterdir()):
        meta_p = d / "meta.json"
        if not meta_p.is_file() or reg.get_estate(db, d.name):
            continue
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            done.append({"estate": d.name, "status": "skipped", "error": f"meta.json unreadable: {e}"})
            continue
        e = reg.create_estate(db, workspace_id, meta.get("name") or d.name, estate_id=d.name, created=meta.get("created"))
        aliases = meta.get("aliases") or {}
        snap = snaps.create(e["id"], label="imported from the data folder", inherit=False, created=meta.get("created"))
        for mn in meta.get("models") or []:
            folder = d / "models" / mn
            al = [a for a, target in aliases.items() if target == mn]
            m = reg.add_model(db, e["id"], mn, aliases=al, created=meta.get("created"))
            for kind in KINDS:
                p = folder / FILE_NAMES[kind]
                if p.is_file():
                    stamp = datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
                    snaps.stage(snap["id"], m["id"], kind, p.read_bytes(), p.name, uploaded_at=stamp)
        run = snaps.process(snap["id"])
        rec = {"estate": e["id"], "name": e["name"], "snapshot": snap["id"], "run": run["status"], "error": run.get("error")}
        if run["status"] == "ok":
            snaps.activate(snap["id"])
            rec["status"] = "active"
        else:
            rec["status"] = "failed"
        done.append(rec)
    return done
