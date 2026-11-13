"""Renaming a model: every record that named it by text follows (pattern statuses, size and plan decisions, proposals,
citations, conversation scopes), so nothing the owner decided reverts to open and every old chip still opens."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from test_web import _B, _upload, settled


class _Cites:
    """Every turn: one get_object call, then an answer citing the line item, its model and a neighbour."""
    def __init__(self): self.messages = self; self.n = 0

    def create(self, **kw):
        self.n += 1
        if self.n % 2 == 1:
            return _B(content=[_B(type="tool_use", id=f"t{self.n}", name="get_object", input={"name": "CAL04 Margin.Margin %"})])
        return _B(content=[_B(type="text", text=f"Turn {self.n // 2}: `CAL04 Margin.Margin %` in `Caldergate Planning` divides by `CAL04 Margin.Net Revenue`.")])


def test_rename_carries_every_decision_citation_and_scope(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Cites)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    old, new = "Caldergate Planning", "Caldergate Plan"
    mid = next(m["id"] for m in c.get(f"/api/estates/{eid}/models").json() if m["name"] == old)
    # the owner's word in every key space that names the model by text, and a conversation scoped to it
    assert c.patch(f"/api/estates/{eid}/findings", json={"key": f"{old}::F-HARDCODE::CAL03 Opex.Bonus", "state": "deliberate", "reason": "policy"}).status_code == 200
    assert c.put(f"/api/estates/{eid}/size/state", json={"model": old, "ref": "CAL02 Revenue.Segment", "state": "keep_current_design", "reason": "board view"}).status_code == 200
    pid = c.post(f"/api/estates/{eid}/plan/proposals", json={"title": "Guard the divide", "model": old, "objects": "CAL04 Margin.Margin %"}).json()["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "what divides?", "scope": {"model": old}}).json()
    cid = conv["id"]; cites = conv["turns"][0]["citations"]
    li = next(x for x in cites if x["kind"] == "line_item"); mdl = next(x for x in cites if x["kind"] == "model")
    assert li["model"] == old and mdl["ref"] == old and len(cites) == 3
    # the rename
    r = c.patch(f"/api/models/{mid}", json={"name": new})
    assert r.status_code == 200 and r.json()["name"] == new
    first = c.get(f"/api/estates/{eid}")                                  # the parse cache is stale: re-read in the background, 409 meanwhile
    assert first.status_code == 409 and first.json()["detail"]["reparsing"] is True and "re-read" in first.json()["detail"]["message"]
    names = [m["name"] for m in settled(c, f"/api/estates/{eid}").json()["models"]]
    assert new in names and old not in names
    st = c.get(f"/api/estates/{eid}/findings").json()
    assert list(st) == [f"{new}::F-HARDCODE::CAL03 Opex.Bonus"] and st[f"{new}::F-HARDCODE::CAL03 Opex.Bonus"]["status"] == "deliberate"
    size = c.get(f"/api/estates/{eid}/size", params={"model": new}).json()
    assert next(x for x in size["over"] if x["ref"] == "CAL02 Revenue.Segment")["decision"]["state"] == "keep_current_design" and size["over_summary"]["decided"] == 1
    plan = c.get(f"/api/estates/{eid}/plan").json()
    prop = next(p for p in plan["proposals"] if p["id"] == pid)
    assert prop["model"] == new and prop["objects_resolved"][0]["kind"] == "line_item" and prop["objects_resolved"][0]["model"] == new
    got = c.get(f"/api/conversations/{cid}").json()
    assert got["scope"] == {"model": new} and {x["model"] for x in got["turns"][0]["citations"]} == {new}
    assert next(x for x in got["turns"][0]["citations"] if x["kind"] == "model")["ref"] == new
    # the old chips still open, under the new name
    ev = c.get(f"/api/citations/{li['id']}").json()
    assert ev["model"] == new and ev["object"]["formula"] and ev["object"]["model"] == new
    assert c.get(f"/api/citations/{mdl['id']}").json()["ref"] == new
    decisions = c.get(f"/api/estates/{eid}/decisions").json()
    assert {d["model"] for d in decisions if d["model"]} == {new} and {d["kind"] for d in decisions} == {"pattern", "size"}
    # the conversation goes on over the renamed estate: its session, plan and size caches were rebuilt
    t = c.post(f"/api/conversations/{cid}/messages", json={"text": "again"}).json()
    assert {x["model"] for x in t["citations"]} == {new} and f"# Model: {new}" in app.state.sessions[cid]._material
    # an action-plan decision follows too (the fixture's only card is on the HR model): action:<kind>:<model>
    hr, hr_new = "Caldergate HR Model", "Caldergate People"
    hr_mid = next(m["id"] for m in c.get(f"/api/estates/{eid}/models").json() if m["name"] == hr)
    card = next(a for a in plan["actions"] if a["model"] == hr)
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": card["state_key"], "state": "investigating", "reason": "Dan"}).status_code == 200
    assert c.patch(f"/api/models/{hr_mid}", json={"name": hr_new}).json()["name"] == hr_new
    settled(c, f"/api/estates/{eid}")
    plan = c.get(f"/api/estates/{eid}/plan").json()
    moved = next(a for a in plan["actions"] if a["state_key"] == card["state_key"].replace(hr, hr_new))
    assert moved["state"]["state"] == "investigating" and moved["state"]["reason"] == "Dan" and not any(a["state_key"] == card["state_key"] for a in plan["actions"])
    assert {d["model"] for d in c.get(f"/api/estates/{eid}/decisions").json() if d["model"]} == {new, hr_new}
