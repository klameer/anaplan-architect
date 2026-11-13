"""v0.2 P4: the demo state is written from files, the same every time, and resetting it touches nothing else."""
import sys, pathlib, json
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def _state(c):
    out = {}
    for eid in ("caldergate-demo", "caldergate-stores-demo"):
        s = c.get(f"/api/estates/{eid}").json()
        docs = c.get(f"/api/estates/{eid}/documents").json()["documents"]
        notes = c.get(f"/api/estates/{eid}/notes").json()
        notes = notes if isinstance(notes, list) else notes["notes"]
        out[eid] = {"name": s["name"], "models": [(m["name"], m["line_items"], m["cells"]) for m in s["models"]],
                    "edges": sorted((e["from"], e["to"], (e.get("state") or {}).get("state")) for e in s["edges"]),
                    "docs": [(d["id"], d["title"], d["summary_by"], [x["id"] for x in d["sections"]], sorted({o["ref"] for o in d["objects"]})) for d in docs],
                    "notes": sorted((n["title"], n["status"], tuple(n["scope_labels"])) for n in notes), "tests": s["tests"]["found"]}
    return out


def test_demo_resets_to_the_same_state_and_leaves_other_workspaces_alone(tmp_path):
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    info = c.get("/api/demo").json()
    assert info["available"] and [w["present"] for w in info["workspaces"]] == [False, False] and len(info["questions"]) >= 7
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    mine = c.post("/api/estates", data={"name": "Mine", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()["id"]
    r = c.post("/api/demo/reset").json()
    assert [w["id"] for w in r["workspaces"]] == ["caldergate-demo", "caldergate-stores-demo"]
    first = _state(c)
    cg = first["caldergate-demo"]
    assert cg["name"] == "Caldergate Distribution Group" and [m[0] for m in cg["models"]] == ["Caldergate Data Hub", "Caldergate FP&A", "Workforce Planning", "Board Reporting"]
    assert sum(m[1] for m in cg["models"]) == 426 and len(cg["docs"]) == 6 and len(cg["notes"]) == 19 and all(d[2] == "author" for d in cg["docs"])
    assert ("Caldergate FP&A", "Workforce Planning", "retired") in cg["edges"]
    assert any("CAL03 Opex.Forecast Opex" in d[4] for d in cg["docs"])
    st = first["caldergate-stores-demo"]
    assert st["models"][0][0] == "Caldergate Store Planning" and st["models"][0][1] == 5403 and st["docs"] == []
    # the count the scripted question asks for is known from the generator: two formats of 24 categories
    q = c.get("/api/estates/caldergate-stores-demo/lineitems", params={"function": "FINDITEM", "group_by": "module", "limit": 3}).json()
    assert q["count"] == 48 and q["of_line_items"] == 5403 and len(q["groups"]["rows"]) == 40
    # a chat in the demo workspace, then a reset: the workspace is as it was first written, the chat is gone, the other workspace is untouched
    c.post("/api/estates/caldergate-demo/documents", files=[("files", ("extra.txt", b"an extra note", "text/plain"))])
    assert len(c.get("/api/estates/caldergate-demo/documents").json()["documents"]) == 7
    c.post("/api/demo/reset")
    assert _state(c) == first
    assert c.get(f"/api/estates/{mine}").json()["name"] == "Mine" and len(c.get("/api/estates").json()) == 3
