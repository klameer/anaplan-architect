"""Orac stage 4: the dependency explorer and the action plan. The counting spec holds on a fixture with a cycle, a
converging path and an incomplete action mapping; the plan carries the owner's state and keeps the architect's
proposals apart from the deterministic cards."""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from fastapi.testclient import TestClient
from anaplan_estate import fleet
from anaplan_architect.orac import deps, plan as planmod, findings_state as fstate
from anaplan_architect.orac.evidence import cite_id
from anaplan_architect.orac.db import Db
from anaplan_architect.orac import estates as reg
from anaplan_architect.store import Workspace
from anaplan_architect import tools
from anaplan_architect.orac.bridge import Bridge
from anaplan_architect.web import create_app
from test_web import _Fake, _upload, FX

DEPS = pathlib.Path(__file__).parent / "fixtures" / "deps"


@pytest.fixture(scope="module")
def er():
    return fleet.run(DEPS)


def _names(nodes):
    return {n["ref"]: n["distance"] for n in nodes}


def test_reach_counts_a_cycle_once_and_excludes_the_selection(er):
    r = deps.reach(er, "Cycle", "CAL01 Flow.A", "downstream", snapshot_id="s1")
    # A -> C -> B -> A: the cycle returns to the selection, which is never counted; each node once
    assert _names(r["nodes"]) == {"CAL01 Flow.C": 1, "OUT01 Report.Total": 1, "CAL01 Flow.B": 2}
    c = r["counts"]
    assert c["line_items"] == 3 and c["direct"] == 2 and c["indirect"] == 1 and c["modules"] == 2 and c["max_distance"] == 2 and c["by_distance"] == {"1": 2, "2": 1}
    assert r["selection"]["id"] == cite_id("s1", "line_item", "Cycle", "CAL01 Flow.A")
    b = next(n for n in r["nodes"] if n["ref"] == "CAL01 Flow.B")
    assert b["via"]["ref"] == "CAL01 Flow.C" and b["id"] == cite_id("s1", "line_item", "Cycle", "CAL01 Flow.B")
    # depth caps the hops
    assert _names(deps.reach(er, "Cycle", "CAL01 Flow.A", "downstream", depth=1)["nodes"]) == {"CAL01 Flow.C": 1, "OUT01 Report.Total": 1}


def test_reach_counts_a_converging_path_once(er):
    r = deps.reach(er, "Cycle", "CAL02 Diamond.W", "downstream")
    # W -> Y, Z -> X -> Total: X is reached twice and counted once, at its shortest distance
    assert _names(r["nodes"]) == {"CAL02 Diamond.Y": 1, "CAL02 Diamond.Z": 1, "CAL02 Diamond.X": 2, "OUT01 Report.Total": 3}
    c = r["counts"]
    assert c["line_items"] == 4 and c["direct"] == 2 and c["indirect"] == 2 and c["modules"] == 2 and c["max_distance"] == 3 and c["footprint_cells"] == 960
    assert [m["ref"] for m in r["modules"]] == ["CAL02 Diamond", "OUT01 Report"] and r["modules"][0]["min_distance"] == 1
    assert c["models"] == 1 and c["models_inferred"] == 0 and r["feeds_inferred"] == []      # Cycle Model feeds nothing
    up = deps.reach(er, "Cycle", "OUT01 Report.Total", "upstream")
    assert _names(up["nodes"]) == {"CAL02 Diamond.X": 1, "CAL01 Flow.A": 1, "CAL02 Diamond.Y": 2, "CAL02 Diamond.Z": 2, "CAL01 Flow.B": 2,
                                   "CAL02 Diamond.W": 3, "SYS01 Settings.Rate": 3, "CAL01 Flow.C": 3}
    assert up["counts"]["line_items"] == 8 and up["counts"]["modules"] == 3
    assert up["counts"]["models_inferred"] == 1 and up["feeds_inferred"][0]["model"] == "Silent" and up["feeds_inferred"][0]["inferred"]


def test_actions_are_listed_at_module_level_and_an_unmatched_target_is_not_placed(er):
    r = deps.reach(er, "Cycle", "CAL02 Diamond.W", "downstream")
    a = r["actions"]
    assert a["level"] == "module" and r["counts"]["actions"] == 2
    by = {x["ref"]: x for x in a["touching"]}
    assert by["Import W from Silent Model - Data"]["module"] == "CAL02 Diamond" and by["Import W from Silent Model - Data"]["direction"] == "writes"
    assert by["Import W from Silent Model - Data"]["on_selection"] and by["Import W from Silent Model - Data"]["processes"] == ["Nightly"]
    assert by["Export Report"]["module"] == "OUT01 Report" and by["Export Report"]["direction"] == "reads" and not by["Export Report"]["on_selection"]
    assert [u["target"] for u in a["unmatched"]] == ["Ghost Module"]
    assert any("cannot be placed" in n for n in r["coverage"])
    # a model with no Actions export: not assessed, never an empty list
    s = deps.reach(er, "Silent", "INP01 Data.V", "downstream")
    assert s["actions"] is None and s["counts"]["actions"] is None and any("No Actions export" in n for n in s["coverage"])
    assert _names(s["nodes"]) == {"CAL01 Calc.R": 1} and s["feeds_inferred"][0]["model"] == "Cycle"


def test_module_reach_excludes_its_own_line_items(er):
    r = deps.reach(er, "Cycle", "CAL02 Diamond", "downstream")
    assert r["selection"]["kind"] == "module" and r["selection"]["line_items"] == 4
    assert _names(r["nodes"]) == {"OUT01 Report.Total": 1} and r["nodes"][0]["via"]["ref"] == "CAL02 Diamond.X"
    up = deps.reach(er, "Cycle", "CAL02 Diamond", "upstream")
    assert _names(up["nodes"]) == {"SYS01 Settings.Rate": 1}
    assert "error" in deps.reach(er, "Cycle", "Nope.Nothing", "downstream") and "error" in deps.reach(er, "Nope", "CAL01 Flow.A")


def test_search_and_graph_neighbourhood(er):
    s = deps.search(er, "rate", snapshot_id="s1")
    assert [h["ref"] for h in s["hits"]] == ["SYS01 Settings.Rate", "CAL02 Diamond.Z"] and s["hits"][0]["in"] == "name" and s["hits"][1]["in"] == "formula"
    assert s["hits"][0]["used_by"] == 1 and s["hits"][0]["id"] == cite_id("s1", "line_item", "Cycle", "SYS01 Settings.Rate")
    d = deps.search(er, "diamond")
    assert d["hits"][0]["kind"] == "module" and d["hits"][0]["line_items"] == 4 and len(d["hits"]) == 6 and d["hits"][-1]["ref"] == "OUT01 Report.Total" and d["hits"][-1]["in"] == "formula"
    assert deps.search(er, "", model="Cycle")["hits"][0]["in"] == "hub"
    assert deps.search(er, "x", kind="module")["hits"] == []
    g = deps.graph(er, "Cycle", "CAL02 Diamond.X", snapshot_id="s1")
    kinds = {n["ref"]: n["kind"] for n in g["nodes"]}
    assert kinds["CAL02 Diamond.X"] == "line_item" and kinds["CAL02 Diamond.Y"] == "line_item" and kinds["OUT01 Report.Total"] == "line_item"
    assert kinds["CAL02 Diamond"] == "module" and kinds["OUT01 Report"] == "module" and kinds["Cycle"] == "model"
    assert kinds["Import W from Silent Model - Data"] == "action" and kinds["Export Report"] == "action" and kinds["Silent"] == "model"
    assert "Import Ghost" not in kinds                                                    # its target is no module here
    types = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
    x, y, tot = (cite_id("s1", "line_item", "Cycle", n) for n in ("CAL02 Diamond.X", "CAL02 Diamond.Y", "OUT01 Report.Total"))
    assert (y, x, "ref") in types and (x, tot, "ref") in types                             # arrows follow the data
    feed = next(e for e in g["edges"] if e["type"] == "feed")
    assert feed["inferred"] and feed["source"] == cite_id("s1", "model", "Silent", "Silent")
    assert next(e for e in g["edges"] if e["type"] == "import")["level"] == "module"
    m = deps.graph(er, "Cycle", "CAL02 Diamond", actions=False, feeds=False)
    assert {n["kind"] for n in m["nodes"]} == {"model", "module", "line_item"} and len([e for e in m["edges"] if e["type"] == "ref"]) == 4


def test_action_states_stay_out_of_pattern_statuses(tmp_path):
    db = Db(tmp_path / "o.db")
    assert db.version >= 7 and "005_proposals.sql" in db.applied
    ws = reg.default_workspace(db); e = reg.create_estate(db, ws, "E")
    fstate.set_state(db, e["id"], "M::F-DIVIDE-FN::x", "accepted", "fine")
    fstate.set_action_state(db, e["id"], "action:retire:M", "investigating", "asked the page builder", by=None, snapshot_id="s1")
    assert set(fstate.as_statuses(db, e["id"])) == {"M::F-DIVIDE-FN::x"}
    assert fstate.action_states(db, e["id"])["action:retire:M"]["state"] == "investigating"
    with pytest.raises(ValueError):
        fstate.set_action_state(db, e["id"], "M::F-DIVIDE-FN::x", "done")
    with pytest.raises(ValueError):
        fstate.set_action_state(db, e["id"], "action:retire:M", "accepted")
    p = planmod.propose(db, e["id"], "Split the heavy formula", "it carries 12% of effort", ["one", " ", "two"], "effort falls", "M", ["CAL.X"], ["c0000000001"], origin="chat_tool")
    assert p["id"].startswith("p-") and p["steps"] == ["one", "two"] and p["citations"] == ["c0000000001"] and not p["withdrawn"]
    assert [x["id"] for x in planmod.list_proposals(db, e["id"])] == [p["id"]]
    planmod.withdraw(db, p["id"])
    assert planmod.list_proposals(db, e["id"]) == [] and planmod.list_proposals(db, e["id"], withdrawn=True)[0]["withdrawn"]
    with pytest.raises(ValueError):
        planmod.propose(db, e["id"], "   ", origin="user")


def test_plan_over_the_fixture_and_the_tools(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws"); w.snapshot_id = "s1"
    sel = planmod.deterministic(w.estate)
    every = sel["candidates"]                                   # the plan (actions) first, then the rest with the reason each is not on it
    assert sel["considered"] >= 1 and all(c["key"] for c in every) and every == sel["actions"] + sel["rest"] and all(c["why_not"] for c in sel["rest"])
    assert len(sel["actions"]) <= sel["top"] and len(every) == sel["considered"]
    cards = planmod.cards(w.estate, sel, "s1", {"action:" + every[0]["key"]: {"state": "done", "reason": "did it", "by": None, "updated": "t", "snapshot_id": "s1"}})
    assert len(cards) == len(every) and [c["on_plan"] for c in cards] == [c in sel["actions"] for c in every]
    assert cards[0]["state"]["state"] == "done" and cards[1:] == [] or cards[1]["state"]["default"]
    assert cards[0]["provenance"] == "observed" and all(o["id"] for o in cards[0]["objects_resolved"]) and cards[0]["state_key"] == "action:" + every[0]["key"]
    assert cards[0]["explorer"] is None or cards[0]["explorer"]["model"] in {m.name for m in w.estate.models}
    with pytest.raises(ValueError):
        planmod.check_objects(w.estate, "Caldergate Planning", ["CAL04 Margin.Margin %", "Nope.Nothing"])
    assert planmod.check_objects(w.estate, "caldergate planning", ["cal04 margin.margin %", "CAL04 Margin"]) == ["CAL04 Margin.Margin %", "CAL04 Margin"]
    # the tools over a store-backed workspace
    db = Db(tmp_path / "o.db"); ws_id = reg.default_workspace(db); e = reg.create_estate(db, ws_id, "Caldergate")
    w.backend = Bridge(db, e["id"], "s1")
    tb = tools.Toolbox(w)
    plan = json.loads(tb.call("action_plan", {"include_below_bar": True}))
    assert plan["considered"] == sel["considered"] and len(plan["actions"]) == len(every) and plan["proposals"] == [] and plan["top"] == sel["top"]
    assert [a["key"] for a in json.loads(tb.call("action_plan", {}))["actions"]] == [c["key"] for c in sel["actions"]]      # without the flag: the plan only
    assert all(a["on_plan"] == (a["key"] in {c["key"] for c in sel["actions"]}) and "group" not in a for a in plan["actions"])
    assert all(a["state"] == "to_review" for a in plan["actions"]) and "cites" in plan
    bad = json.loads(tb.call("propose_action", {"title": "T", "why": "w", "steps": "a\nb", "done_when": "d", "model": "Caldergate Planning", "objects": "CAL04 Margin.Margin %, Ghost.Nope"}))
    assert "error" in bad and "Ghost.Nope" in bad["error"]
    ok = json.loads(tb.call("propose_action", {"title": "Split Margin %", "why": "w", "steps": "a\nb", "done_when": "d", "model": "Caldergate Planning", "objects": "CAL04 Margin.Margin %"}))
    assert ok["state"] == "unconfirmed" and ok["objects"] == ["CAL04 Margin.Margin %"] and ok["cites"]["CAL04 Margin.Margin %"] == cite_id("s1", "line_item", "Caldergate Planning", "CAL04 Margin.Margin %")
    pid = ok["proposal"]
    assert planmod.get_proposal(db, pid)["citations"] == [cite_id("s1", "line_item", "Caldergate Planning", "CAL04 Margin.Margin %")]
    st = json.loads(tb.call("set_action_state", {"key": "proposal:" + pid, "state": "investigating", "reason": "owner said so"}))
    assert st["set"]["state"] == "investigating"
    assert "error" in json.loads(tb.call("set_action_state", {"key": "nope", "state": "done", "reason": ""}))
    assert "error" in json.loads(tb.call("set_action_state", {"key": "proposal:" + pid, "state": "accepted", "reason": ""}))
    if every:                                                   # a decision can be recorded on any candidate, on the plan or under it
        k = every[0]["key"]
        assert json.loads(tb.call("set_action_state", {"key": k, "state": "done", "reason": "r"}))["set"]["key"] == "action:" + k
        assert json.loads(tb.call("action_plan", {"include_below_bar": True}))["actions"][0]["state"] == "done"
    assert w.backend.statuses() == {}                                                     # action decisions never read as pattern statuses
    assert json.loads(tb.call("action_plan", {}))["proposals"][0]["state"] == "investigating"


def test_web_deps_and_plan_routes(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    s = c.get(f"/api/estates/{eid}/deps/search", params={"q": "margin"}).json()
    assert s["hits"] and all(h["id"] for h in s["hits"]) and any(h["ref"] == "CAL04 Margin.Margin %" for h in s["hits"])
    assert c.get(f"/api/estates/{eid}/deps/search", params={"q": "margin", "kind": "module"}).json()["hits"][0]["kind"] == "module"
    r = c.get(f"/api/estates/{eid}/deps/reach", params={"ref": "CAL04 Margin.Margin %", "model": "Caldergate Planning", "direction": "upstream"}).json()
    assert r["counts"]["line_items"] >= 2 and r["selection"]["kind"] == "line_item" and r["coverage"]
    sid = c.get(f"/api/estates/{eid}").json()["snapshot"]["id"]
    assert r["selection"]["id"] == cite_id(sid, "line_item", "Caldergate Planning", "CAL04 Margin.Margin %")
    assert c.get(f"/api/estates/{eid}/deps/reach", params={"ref": "Nope.Nothing", "model": "Caldergate Planning"}).status_code == 404
    g = c.get(f"/api/estates/{eid}/deps/graph", params={"ref": "CAL04 Margin.Margin %", "model": "Caldergate Planning"}).json()
    assert g["centre"] == r["selection"]["id"] and any(n["kind"] == "module" for n in g["nodes"])
    # the object behind a graph node opens in the drawer by the same id
    ev = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL04 Margin.Margin %", "model": "Caldergate Planning", "kind": "line_item"}).json()
    assert ev["id"] == g["centre"]
    # the plan
    p = c.get(f"/api/estates/{eid}/plan").json()
    assert p["states"] == list(fstate.ACTION_STATES) and p["proposals"] == [] and p["considered"] >= 1 and p["tally"]["to_review"] == len(p["actions"])
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": "action:nope", "state": "done"}).status_code == 404
    if p["actions"]:
        k = p["actions"][0]["state_key"]
        assert c.put(f"/api/estates/{eid}/plan/state", json={"key": k, "state": "keep_current_design", "reason": "it is the model's job"}).json()["state"] == "keep_current_design"
        assert c.put(f"/api/estates/{eid}/plan/state", json={"key": k, "state": "accepted"}).status_code == 400
        p2 = c.get(f"/api/estates/{eid}/plan").json()
        assert p2["actions"][0]["state"]["state"] == "keep_current_design" and p2["actions"][0]["state"]["reason"] == "it is the model's job" and p2["tally"]["keep_current_design"] == 1
    bad = c.post(f"/api/estates/{eid}/plan/proposals", json={"title": "Do X", "model": "Caldergate Planning", "objects": "Ghost.Nope"})
    assert bad.status_code == 400 and "Ghost.Nope" in bad.json()["detail"]
    ok = c.post(f"/api/estates/{eid}/plan/proposals", json={"title": "Do X", "why": "because", "steps": "one\ntwo", "done_when": "d", "model": "Caldergate Planning", "objects": "CAL04 Margin.Margin %"}).json()
    assert ok["origin_kind"] == "user" and ok["provenance"] == "not_established" and ok["state"] is None and ok["objects_resolved"][0]["kind"] == "line_item" and ok["steps"] == ["one", "two"]
    p3 = c.get(f"/api/estates/{eid}/plan").json()
    assert [x["id"] for x in p3["proposals"]] == [ok["id"]] and p3["unconfirmed"] == 1
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": "proposal:" + ok["id"], "state": "investigating", "reason": "ok"}).json()["state"] == "investigating"
    assert c.get(f"/api/estates/{eid}/plan").json()["proposals"][0]["state"]["state"] == "investigating"
    assert c.delete(f"/api/estates/{eid}/plan/proposals/{ok['id']}").json()["withdrawn"] and c.get(f"/api/estates/{eid}/plan").json()["proposals"] == []
    assert c.delete(f"/api/estates/{eid}/plan/proposals/p-0000000000").status_code == 404
    assert c.get(f"/api/estates/{eid}").json()["statuses"] == 0                           # action decisions are not pattern statuses
