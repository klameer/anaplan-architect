"""The demo story (2026-09-28): what the seven-step walkthrough needed that the stages had not built.
A feed between models is inferred from import names until the owner confirms or retires it, and the
state travels with the edge everywhere it is shown; the chat `impact` tool reads the explorer's full
reach; a decision on a pattern carries its reason into the drawer; an over-dimensioned line item on
the Size page takes a decision that the size tool then keeps apart."""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import findings_state as fstate
from anaplan_architect.orac.evidence import cite_id
from anaplan_architect import tools
from test_web import _Fake, _upload


def _app(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    return app, c, eid


def _workspace(app, eid):
    return app.state.workspaces[(eid, next(k for k in app.state.workspaces if k[0] == eid)[1])]


def test_a_feed_is_inferred_until_the_owner_confirms_or_retires_it(tmp_path):
    app, c, eid = _app(tmp_path)
    s = c.get(f"/api/estates/{eid}").json()
    e = s["edges"][0]
    assert e["from"] == "Caldergate Planning" and e["to"] == "Caldergate HR Model" and e["state"] is None
    # only a feed the import names show can be marked
    assert c.put(f"/api/estates/{eid}/edges", json={"from": e["to"], "to": e["from"], "state": "confirmed", "reason": "x"}).status_code == 404
    r = c.put(f"/api/estates/{eid}/edges", json={"from": e["from"], "to": e["to"], "state": "confirmed", "reason": "runs in the monthly refresh"})
    assert r.status_code == 200 and r.json()["state"]["state"] == "confirmed"
    s = c.get(f"/api/estates/{eid}").json()
    assert s["edges"][0]["state"]["state"] == "confirmed" and s["edges"][0]["state"]["reason"] == "runs in the monthly refresh"
    # it is not a pattern status, and it reaches the tools, the material and the drawer
    assert c.get(f"/api/estates/{eid}/findings").json() == {}
    w = c.app.state.workspaces[next(k for k in c.app.state.workspaces if k[0] == eid)]
    tb = tools.Toolbox(w)
    lm = tb.list_models()
    assert lm["edges"][0]["state"] == "confirmed" and lm["edges"][0]["reason"] == "runs in the monthly refresh"
    from anaplan_architect.material import estate_material
    assert "[confirmed by the owner: runs in the monthly refresh]" in estate_material(w)
    ev = c.get(f"/api/estates/{eid}/object", params={"ref": "Caldergate Planning", "kind": "model"})
    assert ev.status_code == 200 and ev.json()["object"]["feeds"][0]["state"]["state"] == "confirmed"
    # the chat tool records the owner's word, and retiring keeps the reason; back to inferred clears the row
    out = tb.set_edge_state("caldergate planning", "Caldergate HR Model", "retired", "nobody has run it since 2024")
    assert out["set"]["state"] == "retired" and "error" not in out
    assert c.get(f"/api/estates/{eid}").json()["edges"][0]["state"]["state"] == "retired"
    assert tb.set_edge_state("Caldergate Planning", "Caldergate HR Model", "inferred", "")["set"] == {"state": "inferred"}
    assert c.get(f"/api/estates/{eid}").json()["edges"][0]["state"] is None
    assert "error" in tb.set_edge_state("Caldergate HR Model", "Caldergate Planning", "confirmed", "no such feed")


def _ws(c, eid):
    return c.app.state.workspaces[next(k for k in c.app.state.workspaces if k[0] == eid)]


def test_a_decision_on_a_pattern_carries_its_reason_into_the_drawer_and_a_card_names_its_objects(tmp_path):
    app, c, eid = _app(tmp_path)
    pid = "Caldergate Planning::F-HARDCODE::CAL03 Opex.Bonus"
    r = c.patch(f"/api/estates/{eid}/findings", json={"key": pid, "state": "deliberate", "reason": "the bonus rate is policy, not a driver"})
    assert r.status_code == 200
    ev = c.get(f"/api/estates/{eid}/object", params={"ref": pid, "kind": "pattern"}).json()["object"]
    assert ev["status"] == "deliberate" and ev["decision"]["reason"] == "the bonus rate is policy, not a driver" and ev["decision"]["when"]
    li = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL03 Opex.Bonus", "model": "Caldergate Planning", "kind": "line_item"}).json()["object"]
    pat = next(p for p in li["patterns"] if p["id"] == pid)
    assert pat["status"] == "deliberate" and pat["decision"]["reason"].startswith("the bonus rate")
    # a line item a plan card names shows the card and its state, before and after the owner decides
    q = {"ref": "CAL01 Headcount Cost.Cost", "model": "Caldergate HR Model", "kind": "line_item"}
    li = c.get(f"/api/estates/{eid}/object", params=q).json()["object"]
    assert li["plan"] and li["plan"][0]["key"] == "action:hotspot-investigate:Caldergate HR Model" and li["plan"][0]["state"]["state"] == "to_review" and li["plan"][0]["state"]["default"]
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": "action:hotspot-investigate:Caldergate HR Model", "state": "investigating", "reason": "Dan is looking"}).status_code == 200
    li = c.get(f"/api/estates/{eid}/object", params=q).json()["object"]
    assert li["plan"][0]["state"]["state"] == "investigating" and li["plan"][0]["state"]["reason"] == "Dan is looking"
    mod = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL01 Headcount Cost", "model": "Caldergate HR Model", "kind": "module"}).json()["object"]
    assert mod["plan"][0]["state"]["reason"] == "Dan is looking"


def test_an_over_dimensioned_line_item_takes_a_decision_the_size_tool_keeps_apart(tmp_path):
    app, c, eid = _app(tmp_path)
    rep = c.get(f"/api/estates/{eid}/size", params={"model": "Caldergate Planning"}).json()
    row = rep["over"][0]
    assert row["ref"] == "CAL02 Revenue.Segment" and row["decision"] is None and row["key"] == "size:Caldergate Planning::CAL02 Revenue.Segment"
    assert c.put(f"/api/estates/{eid}/size/state", json={"model": "Caldergate Planning", "ref": "Nope.Nope", "state": "done", "reason": ""}).status_code == 404
    r = c.put(f"/api/estates/{eid}/size/state", json={"model": "Caldergate Planning", "ref": "CAL02 Revenue.Segment", "state": "keep_current_design", "reason": "shown per region on the board view"})
    assert r.status_code == 200 and r.json()["state"] == "keep_current_design"
    rep = c.get(f"/api/estates/{eid}/size", params={"model": "Caldergate Planning"}).json()
    assert rep["over"][0]["decision"]["state"] == "keep_current_design" and rep["over_summary"]["decided"] == 1
    assert c.get(f"/api/estates/{eid}/findings").json() == {}                       # not a pattern status
    tb = tools.Toolbox(_ws(c, eid))
    out = tb.size(model="Caldergate Planning")
    assert out["over_dimensioned"] == [] and out["decided"][0]["ref"] == "CAL02 Revenue.Segment" and out["decided"][0]["reason"] == "shown per region on the board view"
    assert out["over_summary"]["decided"] == 1
    one = tb.size(model="Caldergate Planning", name="CAL02 Revenue.Segment")
    assert one["decision"]["state"] == "keep_current_design" and one["key"] == row["key"]
    # the chat tool records a decision on a size row by its key; the drawer's axes block shows it
    res = tb.set_action_state("size:caldergate planning::CAL02 Revenue.Segment", "done", "reduced in the dev copy")
    assert "error" not in res and res["set"]["state"] == "done"
    assert c.get(f"/api/estates/{eid}/size/item", params={"model": "Caldergate Planning", "ref": "CAL02 Revenue.Segment"}).json()["decision"]["state"] == "done"
    axes = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL02 Revenue.Segment", "model": "Caldergate Planning", "kind": "line_item"}).json()["object"]["axes"]
    assert axes["decision"]["state"] == "done" and axes["decision"]["reason"] == "reduced in the dev copy"
    assert "error" in tb.set_action_state("size:Caldergate Planning::Nope.Nope", "done", "x")


def test_the_chat_impact_tool_reads_the_whole_reach(tmp_path):
    from anaplan_estate import fleet
    from anaplan_architect.store import Workspace
    er = fleet.run(pathlib.Path(__file__).parent / "fixtures" / "deps")
    w = Workspace.from_run(er, tmp_path / "ws"); w.snapshot_id = "s1"
    tb = tools.Toolbox(w)
    out = json.loads(tb.call("impact", {"name": "CAL01 Flow.A", "model": "Cycle"}))
    assert out["counts"]["line_items"] == 3 and out["counts"]["direct"] == 2 and out["counts"]["modules"] == 2 and out["depth"] is None
    assert {n["ref"] for n in out["line_items"]} == {"CAL01 Flow.C", "OUT01 Report.Total", "CAL01 Flow.B"}
    assert out["cites"]["CAL01 Flow.B"] == cite_id("s1", "line_item", "Cycle", "CAL01 Flow.B") and "OUT01 Report" in out["cites"]
    assert out["coverage"] and out["limits"]
    up = json.loads(tb.call("impact", {"name": "OUT01 Report.Total", "model": "Cycle", "direction": "upstream"}))
    assert up["counts"]["line_items"] == 8 and up["other_models"][0]["model"] == "Silent" and up["other_models"][0]["state"] == "inferred"
    mod = json.loads(tb.call("impact", {"name": "CAL02 Diamond", "model": "Cycle"}))
    assert mod["kind"] == "module" and mod["selection"] == "CAL02 Diamond" and mod["counts"]["line_items"] >= 1
    capped = json.loads(tb.call("impact", {"name": "CAL01 Flow.A", "model": "Cycle", "depth": 1}))
    assert capped["counts"]["line_items"] == 2 and capped["depth"] == 1


def test_a_scoped_note_carries_its_object_citation_and_decisions_are_listed_in_one_place(tmp_path):
    app, c, eid = _app(tmp_path)
    r = c.post(f"/api/estates/{eid}/notes", json={"title": "Bonus is policy", "body": "The bonus rate is policy, not a driver.", "type": "constraint", "status": "user_confirmed",
                                                   "objects": ["Caldergate Planning::CAL03 Opex.Bonus", "model:Caldergate Planning", "Caldergate Planning::CAL03 Opex"]})
    assert r.status_code == 200
    n = r.json()
    got = {(s["kind"], s["ref"], s["tool"]) for s in n["sources_resolved"]}
    assert got == {("line_item", "CAL03 Opex.Bonus", "scope"), ("model", "Caldergate Planning", "scope"), ("module", "CAL03 Opex", "scope")}
    li = next(s for s in n["sources_resolved"] if s["kind"] == "line_item")
    ev = c.get(f"/api/citations/{li['id']}")
    assert ev.status_code == 200 and ev.json()["object"]["ref"] == "CAL03 Opex.Bonus" and ev.json()["cited_in"]["notes"][0]["id"] == n["id"]
    # a note about the whole estate carries nothing; re-scoping replaces what it carries
    n2 = c.patch(f"/api/notes/{n['id']}", json={"objects": ["estate"]}).json()
    assert n2["sources_resolved"] == [] and n2["sources"] == []
    n3 = c.patch(f"/api/notes/{n['id']}", json={"objects": ["Caldergate Planning::CAL03 Opex"]}).json()
    assert [(s["kind"], s["ref"]) for s in n3["sources_resolved"]] == [("module", "CAL03 Opex")]
    # decisions of every kind in one list, each named and carrying its reason
    e = c.get(f"/api/estates/{eid}").json()["edges"][0]
    assert c.patch(f"/api/estates/{eid}/findings", json={"key": "Caldergate Planning::F-HARDCODE::CAL03 Opex.Bonus", "state": "deliberate", "reason": "policy"}).status_code == 200
    assert c.put(f"/api/estates/{eid}/edges", json={"from": e["from"], "to": e["to"], "state": "confirmed", "reason": "monthly refresh"}).status_code == 200
    assert c.put(f"/api/estates/{eid}/size/state", json={"model": "Caldergate Planning", "ref": "CAL02 Revenue.Segment", "state": "keep_current_design", "reason": "board view"}).status_code == 200
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": "action:hotspot-investigate:Caldergate HR Model", "state": "investigating", "reason": "Dan"}).status_code == 200
    d = c.get(f"/api/estates/{eid}/decisions").json()
    by = {x["kind"]: x for x in d}
    assert set(by) == {"pattern", "connection", "size", "action"} and len(d) == 4
    assert by["pattern"]["label"] == "CAL03 Opex.Bonus" and by["pattern"]["rule"] == "F-HARDCODE" and by["pattern"]["state"] == "deliberate" and by["pattern"]["reason"] == "policy"
    assert by["connection"]["model"] == "Caldergate Planning" and by["connection"]["to"] == "Caldergate HR Model" and by["connection"]["state"] == "confirmed"
    assert by["size"]["label"] == "CAL02 Revenue.Segment" and by["size"]["object"]["kind"] == "line_item" and by["size"]["model"] == "Caldergate Planning"
    assert by["action"]["label"].startswith("Look at the five heaviest") and by["action"]["reason"] == "Dan"
