"""A stale parse cache (review item 9): one load per snapshot at a time; with a refresher the re-read runs in the
background and requests answer 409 until it is done; without one (the CLI, most tests) it is parsed in place; an
activation compares its notes without waiting on the page."""
import sys, pathlib
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.orac.snapshots import Snapshots, Reparsing
from anaplan_architect.orac.jobs import Jobs
from anaplan_architect.orac import estates as reg
from test_orac import store, _estate


def test_a_stale_cache_is_reread_in_the_background_or_in_place(tmp_path):
    db, blobs, snaps = store(tmp_path)
    e, p, h, s = _estate(db, snaps, reg.default_workspace(db))
    assert snaps.process(s["id"])["status"] == "ok"
    snaps.activate(s["id"])
    jobs = Jobs(snaps)
    snaps.refresher = jobs.refresh
    assert [m.name for m in snaps.estate_run(s["id"]).models] == ["Caldergate Planning", "Caldergate HR"]
    reg.update_model(db, h["id"], name="Caldergate People")                  # the names are part of the cache key
    snaps._forget(s["id"])
    with pytest.raises(Reparsing):
        snaps.estate_run(s["id"])                                             # not parsed here: handed to the worker
    jobs.wait_refresh(s["id"])
    assert [m.name for m in snaps.estate_run(s["id"]).models] == ["Caldergate Planning", "Caldergate People"]
    reg.update_model(db, h["id"], name="Caldergate Staff")
    snaps._forget(s["id"])
    assert [m.name for m in snaps.estate_run(s["id"], block=True).models] == ["Caldergate Planning", "Caldergate Staff"]   # block: parsed now
    jobs.shutdown()
