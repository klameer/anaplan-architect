"""Restore reads an archive anyone with an account can upload: entry names and ids are text, never paths."""
import sys, pathlib, json, zipfile
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.orac.db import Db
from anaplan_architect.orac.blobs import BlobStore
from anaplan_architect.orac import backup, estates as reg


def _archive(path, estate_id="e-1", extra=()):
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
    assert not list(tmp_path.rglob("escaped*.txt")) and reg.get_estate(db, "e-1") is None
    with pytest.raises(ValueError, match="not a plain id"):
        backup.import_estate(db, blobs, data, _archive(tmp_path / "badid.zip", estate_id="../../outside"), ws)
    assert not (tmp_path / "outside").exists() and not (tmp_path / "estates").exists()
    ok = _archive(tmp_path / "ok.zip", extra=[("architect/transcripts/c-1.jsonl", "{}")])
    r = backup.import_estate(db, blobs, data, ok, ws)
    assert r["id"] == "e-1" and (data / "estates" / "e-1" / ".architect" / "transcripts" / "c-1.jsonl").exists()
