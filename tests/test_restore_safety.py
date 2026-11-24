"""Restore reads an archive anyone with an account can upload: entry names and ids are text, never paths."""
import sys, pathlib, json, zipfile
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.orac.db import Db
from anaplan_architect.orac.blobs import BlobStore
from anaplan_architect.orac import backup, estates as reg


EID = "20260929-100000-abcd"


def _archive(path, estate_id=EID, extra=()):
    tables = {"estates": [{"id": estate_id, "workspace_id": "x", "name": "E", "created_by": None, "created": "2026-09-29T10:00:00", "archived": 0}]}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.KIND, "format": backup.FORMAT, "estate_id": estate_id, "name": "E", "counts": {}}))
        for t, rows in tables.items():
            z.writestr(f"tables/{t}.json", json.dumps(rows))
        for name, body in extra:
            z.writestr(name, body)
    return path


def test_restore_refuses_paths_and_ids_that_leave_the_estate_folder(tmp_path):
    db = Db(tmp_path / "orac.db"); blobs = BlobStore(tmp_path / "blobs", db); ws = reg.default_workspace(db)
    data = tmp_path / "data"
    evil = _archive(tmp_path / "evil.zip", extra=[("architect/transcripts/../../../../escaped.txt", "x"), ("architect\\..\\..\\escaped2.txt", "x")])
    with pytest.raises(ValueError, match="leave its folder"):
        backup.import_estate(db, blobs, data, evil, ws)
    assert not list(tmp_path.rglob("escaped*.txt")) and reg.get_estate(db, EID) is None and db.one("SELECT COUNT(*) AS n FROM estates")["n"] == 0
    for bad in ("../../outside", "e-1", EID.upper(), EID + ".", "CON", "create"):
        with pytest.raises(ValueError, match="not in the shape"):
            backup.import_estate(db, blobs, data, _archive(tmp_path / "badid.zip", estate_id=bad), ws)
    assert not (tmp_path / "outside").exists() and not (tmp_path / "estates").exists()
    for name in ("architect/transcripts/NUL.jsonl", "architect/transcripts/c-1.jsonl.", "architect/transcripts/c:1.jsonl", "architect/con/x.jsonl"):
        with pytest.raises(ValueError, match="leave its folder"):
            backup.import_estate(db, blobs, data, _archive(tmp_path / "odd.zip", extra=[(name, "x")]), ws)
    ok = _archive(tmp_path / "ok.zip", extra=[("architect/transcripts/c-1.jsonl", "{}")])
    r = backup.import_estate(db, blobs, data, ok, ws)
    # the workspace's id, and so its folder, is the server's: never the one the archive names (security review 2026-11-24, M2)
    assert r["id"] != EID and reg.get_estate(db, EID) is None and not (data / "estates" / EID).exists()
    assert (data / "estates" / r["id"] / ".architect" / "transcripts" / "c-1.jsonl").exists()
    r2 = backup.import_estate(db, blobs, data, ok, ws)
    assert r2["id"] not in (EID, r["id"]) and len(list((data / "estates").iterdir())) == 2
