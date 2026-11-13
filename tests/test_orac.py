import sys, pathlib, json, zipfile, io
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from anaplan_architect.orac.db import Db
from anaplan_architect.orac.blobs import BlobStore
from anaplan_architect.orac.snapshots import Snapshots
from anaplan_architect.orac.jobs import Jobs
from anaplan_architect.orac.legacy import import_legacy
from anaplan_architect.orac import estates as reg

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"
PLAN = FX / "1 Caldergate Planning"
HR = FX / "2 Caldergate HR Model"


def store(tmp_path):
    db = Db(tmp_path / "orac.db")
    blobs = BlobStore(tmp_path / "blobs", db)
    return db, blobs, Snapshots(db, blobs, tmp_path)


def test_migrations_apply_once(tmp_path):
    db = Db(tmp_path / "o.db")
    from anaplan_architect.orac.db import MIGRATIONS
    every = sorted(f.name for f in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    assert db.applied == every and every[:7] == ["001_core.sql", "002_identity.sql", "003_notes_conversations.sql", "004_verification.sql", "005_proposals.sql",
                                                 "006_freshness.sql", "007_tracing.sql"] and db.version == len(every)
    again = Db(tmp_path / "o.db")
    assert again.applied == [] and again.version == len(every)
    assert {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")} >= {"estates", "models", "snapshots", "snapshot_files", "parse_runs", "blobs", "audit"}


def test_blobs_dedupe_and_gc(tmp_path):
    db, blobs, _ = store(tmp_path)
    a = blobs.put(b"abc"); b = blobs.put(b"abc")
    assert a == b and blobs.get(a) == b"abc" and blobs.size(a) == 3 and blobs.path(a).exists()
    assert blobs.gc() == 1 and not blobs.path(a).exists() and blobs.size(a) is None


def test_register(tmp_path):
    db, _, _ = store(tmp_path)
    ws = reg.default_workspace(db)
    assert ws == "local" and reg.default_workspace(db) == "local"
    e = reg.create_estate(db, ws, "Group")
    m = reg.add_model(db, e["id"], "FP&A", purpose="planning", owner="Ana", aliases=["FPA", "Finance model"])
    assert m["aliases"] == ["FPA", "Finance model"] and m["seq"] == 1
    assert reg.find_model(db, e["id"], "fpa")["id"] == m["id"]                 # alias, case-insensitive
    assert reg.find_model(db, e["id"], "FP&A Model")["id"] == m["id"]          # folder-cleaned form
    with pytest.raises(ValueError):
        reg.add_model(db, e["id"], "fp&a")
    with pytest.raises(ValueError):
        reg.add_model(db, e["id"], "///")
    m2 = reg.update_model(db, m["id"], purpose="budgeting", aliases=["FPA"], retired=True)
    assert m2["purpose"] == "budgeting" and m2["aliases"] == ["FPA"] and m2["retired"]
    assert reg.aliases_map(db, e["id"]) == {"FPA": "FP&A"}
    assert reg.list_models(db, e["id"], include_retired=False) == []
    reg.update_estate(db, e["id"], name="Group planning", archived=True)
    assert reg.list_estates(db, ws) == [] and reg.get_estate(db, e["id"])["name"] == "Group planning"
    assert [a["action"] for a in db.q("SELECT action FROM audit ORDER BY id")][:2] == ["estate.create", "model.add"]


def _estate(db, snaps, ws):
    e = reg.create_estate(db, ws, "Caldergate")
    p = reg.add_model(db, e["id"], "Caldergate Planning")
    h = reg.add_model(db, e["id"], "Caldergate HR")
    s = snaps.create(e["id"], label="first")
    for m, d in ((p, PLAN), (h, HR)):
        snaps.stage(s["id"], m["id"], "line_items", (d / "Line Items.csv").read_bytes(), "Line Items.csv")
        snaps.stage(s["id"], m["id"], "actions", (d / "Actions.csv").read_bytes(), "Actions.csv")
    return e, p, h, s


def test_snapshot_flow_and_failure_keeps_active(tmp_path):
    db, blobs, snaps = store(tmp_path)
    ws = reg.default_workspace(db)
    e, p, h, s = _estate(db, snaps, ws)
    assert snaps.get(s["id"])["status"] == "draft" and snaps.ready(s["id"]) == []
    with pytest.raises(ValueError):
        snaps.activate(s["id"])                                   # not processed yet
    run = snaps.process(s["id"])
    assert run["status"] == "ok", run["error"]
    assert set(run["stats"]["models"]) == {"Caldergate Planning", "Caldergate HR"} and run["stats"]["edges"] == 1
    assert run["coverage"]["Caldergate HR"]["files"]["actions"] == "Actions.csv"
    assert snaps.get(s["id"])["status"] == "processed"
    snaps.activate(s["id"])
    assert snaps.active(e["id"])["id"] == s["id"]
    er = snaps.estate_run(s["id"])
    assert [m.name for m in er.models] == ["Caldergate Planning", "Caldergate HR"] and er.edges[0]["from"] == "Caldergate Planning"
    with pytest.raises(ValueError):
        snaps.stage(s["id"], p["id"], "actions", b"x", "Actions.csv")   # an active snapshot's files never change
    # second snapshot: inherits every file, replaces HR's Line Items with a broken one
    s2 = snaps.create(e["id"], label="HR refresh")
    assert {(f["model"], f["kind"]) for f in s2["files"]} == {("Caldergate Planning", "line_items"), ("Caldergate Planning", "actions"),
                                                              ("Caldergate HR", "line_items"), ("Caldergate HR", "actions")}
    f = snaps.stage(s2["id"], h["id"], "line_items", b"Module,Name\nA,B\n", "Line Items.csv")
    assert f["problem"] and "Formula" in f["problem"]
    assert snaps.ready(s2["id"]) and snaps.ready(s2["id"])[0].startswith("Caldergate HR")
    run2 = snaps.process(s2["id"])
    assert run2["status"] == "failed" and "Formula" in run2["error"]
    assert snaps.get(s2["id"])["status"] == "failed" and snaps.active(e["id"])["id"] == s["id"]    # the previous snapshot still serves
    # fix it with a good file carrying its own date; every other file keeps the date it was uploaded with
    snaps.stage(s2["id"], h["id"], "line_items", (HR / "Line Items.csv").read_bytes(), "Line Items.csv", uploaded_at="2026-09-25T09:00:00")
    assert snaps.get(s2["id"])["status"] == "draft"
    assert snaps.process(s2["id"])["status"] == "ok"
    snaps.activate(s2["id"])
    old = snaps.get(s["id"])
    assert old["status"] == "superseded" and old["superseded_at"]
    act = snaps.active(e["id"])
    dates = {(x["model"], x["kind"]): x["uploaded_at"] for x in act["files"]}
    assert dates[("Caldergate HR", "line_items")] == "2026-09-25T09:00:00" and dates[("Caldergate Planning", "line_items")] != "2026-09-25T09:00:00"
    assert len(db.q("SELECT * FROM blobs")) == 5                 # four fixture files once each, plus the broken one
    from anaplan_architect.orac import conversations as convs
    held = convs.create(db, e["id"], "held on the first snapshot", s["id"])
    with pytest.raises(ValueError):
        snaps.delete(s["id"])                                     # a superseded snapshot is kept while a conversation is held on it
    convs.delete(db, held["id"])
    root, names = snaps.materialise(s2["id"])
    assert sorted(d.name for d in root.iterdir() if d.is_dir()) == [f"001 {p['id']}", f"002 {h['id']}"] and names[p["id"]] == "Caldergate Planning"
    assert blobs.gc() == 1 and len(db.q("SELECT * FROM blobs")) == 4     # the broken file was replaced in the draft: nothing references it now
    assert [x["status"] for x in snaps.list(e["id"])] == ["active", "superseded"]


def test_jobs_run_in_the_background(tmp_path):
    db, blobs, snaps = store(tmp_path)
    e, p, h, s = _estate(db, snaps, reg.default_workspace(db))
    jobs = Jobs(snaps)
    run = jobs.submit(s["id"])
    assert run["status"] in ("running", "ok")
    assert jobs.wait(s["id"])["status"] == "ok" and snaps.get(s["id"])["status"] == "processed"
    assert jobs.submit(s["id"])["status"] in ("running", "ok")     # a second run is allowed once the first is done
    jobs.wait(s["id"])
    jobs.shutdown()


def test_zip_import_and_rename(tmp_path):
    db, blobs, snaps = store(tmp_path)
    ws = reg.default_workspace(db)
    e = reg.create_estate(db, ws, "Z")
    s = snaps.create(e["id"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for d in FX.iterdir():
            for f in d.iterdir():
                z.writestr(f"{d.name}/{f.name}", f.read_bytes())
        z.writestr("notes.txt", "ignored")
    zp = tmp_path / "estate.zip"
    zp.write_bytes(buf.getvalue())
    staged = snaps.stage_zip(s["id"], zp, make_model=lambda n: reg.add_model(db, e["id"], n))
    assert len(staged) == 4 and {x["model"] for x in staged} == {"Caldergate Planning", "Caldergate HR"}    # folder names cleaned as fleet does
    assert snaps.process(s["id"])["status"] == "ok"
    snaps.activate(s["id"])
    m = reg.find_model(db, e["id"], "Caldergate HR")
    reg.update_model(db, m["id"], name="People")
    snaps._forget(s["id"])
    assert "People" in [x.name for x in snaps.estate_run(s["id"]).models]
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ValueError):
        snaps.stage_zip(snaps.create(e["id"])["id"], bad, make_model=lambda n: None)


def test_legacy_import(tmp_path):
    data = tmp_path / "data"
    old = data / "estates" / "20260922-080633-daa6"
    for src, name in ((PLAN, "Caldergate Planning"), (HR, "HR")):
        (old / "models" / name).mkdir(parents=True)
        for f in src.iterdir():
            (old / "models" / name / f.name).write_bytes(f.read_bytes())
    (old / "meta.json").write_text(json.dumps({"name": "Old estate", "models": ["Caldergate Planning", "HR"], "aliases": {"Headcount Model": "HR"},
                                               "created": "2026-09-22T08:06:33"}), encoding="utf-8")
    (old / ".architect" / "transcripts").mkdir(parents=True)
    (old / ".architect" / "transcripts" / "x.jsonl").write_text('{"role":"title","text":"kept"}\n', encoding="utf-8")
    db = Db(data / "orac.db"); blobs = BlobStore(data / "blobs", db); snaps = Snapshots(db, blobs, data)
    ws = reg.default_workspace(db)
    done = import_legacy(db, blobs, snaps, data, ws)
    assert [d["status"] for d in done] == ["active"] and done[0]["estate"] == "20260922-080633-daa6"
    e = reg.get_estate(db, "20260922-080633-daa6")
    assert e["name"] == "Old estate" and e["created"] == "2026-09-22T08:06:33"
    ms = reg.list_models(db, e["id"])
    assert [m["name"] for m in ms] == ["Caldergate Planning", "HR"] and ms[1]["aliases"] == ["Headcount Model"]
    act = snaps.active(e["id"])
    assert act["label"] == "imported from the data folder" and len(act["files"]) == 4
    assert import_legacy(db, blobs, snaps, data, ws) == []                                   # once only
    assert (old / "meta.json").exists() and (old / ".architect" / "transcripts" / "x.jsonl").exists()   # nothing deleted


def test_estate_run_uses_the_disk_cache(tmp_path, monkeypatch):
    db, blobs, snaps = store(tmp_path)
    e, p, h, s = _estate(db, snaps, reg.default_workspace(db))
    assert snaps.process(s["id"])["status"] == "ok"
    snaps.activate(s["id"])
    root = snaps.root(s["id"])
    assert (root / "estate.pkl").exists() and (root / "estate.key").exists()
    fresh = Snapshots(db, blobs, tmp_path)                      # a restart: nothing in memory
    from anaplan_estate import fleet
    monkeypatch.setattr(fleet, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parsed again")))
    er = fresh.estate_run(s["id"])
    assert [m.name for m in er.models] == ["Caldergate Planning", "Caldergate HR"]
    reg.update_model(db, h["id"], aliases=["People"])           # aliases are part of the key: the cache no longer applies
    fresh._forget(s["id"])
    with pytest.raises(AssertionError):
        fresh.estate_run(s["id"])


def test_subprocess_parse_and_cancel(tmp_path):
    db, blobs, _ = store(tmp_path)
    snaps = Snapshots(db, blobs, tmp_path, subprocess=True)
    e, p, h, s = _estate(db, snaps, reg.default_workspace(db))
    run = snaps.process(s["id"])
    assert run["status"] == "ok", run["error"]
    assert set(run["stats"]["models"]) == {"Caldergate Planning", "Caldergate HR"} and (snaps.root(s["id"]) / "estate.pkl").exists()
    assert [m.name for m in snaps.estate_run(s["id"]).models] == ["Caldergate Planning", "Caldergate HR"]
    s2 = snaps.create(e["id"], label="cancel me", inherit=False)
    for m, d in ((p, PLAN), (h, HR)):
        snaps.stage(s2["id"], m["id"], "line_items", (d / "Line Items.csv").read_bytes(), "Line Items.csv")
    run2 = snaps.process(s2["id"], cancelled=lambda: True)        # cancel flagged while the worker runs: terminated, discarded
    assert run2["status"] == "cancelled" and snaps.get(s2["id"])["status"] == "draft"
    assert snaps.active(e["id"]) is None and snaps.get(s["id"])["status"] == "processed"
