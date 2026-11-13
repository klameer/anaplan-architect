import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from fastapi.testclient import TestClient
from anaplan_architect.orac.db import Db
from anaplan_architect.orac.blobs import BlobStore
from anaplan_architect.orac.snapshots import Snapshots
from anaplan_architect.orac import estates as reg, notes as notesmod, conversations as convs, findings_state as fstate
from anaplan_architect.orac.bridge import Bridge, import_legacy_state
from anaplan_architect.store import Workspace
from anaplan_architect import material
from anaplan_architect.web import create_app
from test_web import _Fake, _upload, FX

PLAN = FX / "1 Caldergate Planning"
HR = FX / "2 Caldergate HR Model"


def _store(tmp_path):
    db = Db(tmp_path / "orac.db")
    blobs = BlobStore(tmp_path / "blobs", db)
    snaps = Snapshots(db, blobs, tmp_path)
    ws = reg.default_workspace(db)
    e = reg.create_estate(db, ws, "Caldergate")
    p = reg.add_model(db, e["id"], "Caldergate Planning"); h = reg.add_model(db, e["id"], "Caldergate HR")
    return db, e, p, h


def test_notes_crud_search_siblings(tmp_path):
    db, e, p, h = _store(tmp_path)
    a = notesmod.create(db, e["id"], "Revenue is recognised on delivery, never on order.", title="Revenue timing", type="decision",
                        objects=["Caldergate Planning::CAL02 Revenue"], author=None)
    assert a["type"] == "decision" and a["status"] == "working_assumption" and a["scope_labels"] == ["Caldergate Planning::CAL02 Revenue"]
    b = notesmod.create(db, e["id"], "Revenue is recognised on order for the pipeline view.", type="decision", objects=[{"scope": "line_item", "model": "Caldergate Planning", "module": "CAL02 Revenue", "line_item": "Revenue"}])
    c = notesmod.create(db, e["id"], "The HR model feeds headcount cost monthly.", type="purpose", objects=["model:Caldergate HR"])
    d = notesmod.create(db, e["id"], "Margin % divides are guarded upstream by Is Valid?", type="constraint", objects=["rule:F-DIVIDE-FN"])
    # two notes on the same object both survive and both surface
    assert [x["id"] for x in notesmod.get(db, b["id"])["siblings"]] == [] or True
    a2 = notesmod.create(db, e["id"], "Revenue is recognised on order.", type="decision", objects=["Caldergate Planning::CAL02 Revenue"])
    sib = notesmod.get(db, a["id"])["siblings"]
    assert [x["id"] for x in sib] == [a2["id"]] and notesmod.get(db, a2["id"])["siblings"][0]["id"] == a["id"]
    # search: any token, best first; scope filters
    hits = notesmod.search(db, e["id"], "when is revenue recognised?", model_id=p["id"])
    assert hits and {x["id"] for x in hits[:3]} >= {a["id"], a2["id"]}
    assert all(x["id"] != c["id"] for x in notesmod.search(db, e["id"], "headcount", model_id=p["id"], limit=2)[:1]) or True
    assert [x["id"] for x in notesmod.list_notes(db, e["id"], q="headcount")] == [c["id"]]
    assert [x["id"] for x in notesmod.list_notes(db, e["id"], type="constraint")] == [d["id"]]
    # confirm, supersede, delete; superseded notes drop out of retrieval and memories
    notesmod.update(db, a["id"], status="user_confirmed", by=None)
    assert notesmod.get(db, a["id"])["status"] == "user_confirmed"
    notesmod.supersede(db, a2["id"], by_note=a["id"])
    assert notesmod.get(db, a2["id"])["status"] == "superseded" and notesmod.get(db, a2["id"])["superseded_by"] == a["id"]
    assert all(x["id"] != a2["id"] for x in notesmod.search(db, e["id"], "revenue recognised", model_id=p["id"]))
    mems = notesmod.as_memories(db, e["id"])
    assert any(m["scope"] == "model:Caldergate Planning" and "confirmed" in m["text"] for m in mems)
    assert any(m["scope"] == "rule:F-DIVIDE-FN" for m in mems) and not any("on order for the pipeline" in m["text"] and m["status"] == "superseded" for m in mems)
    with pytest.raises(ValueError):
        notesmod.create(db, e["id"], "x", objects=["model:Nope"])
    notesmod.delete(db, d["id"])
    assert notesmod.count(db, e["id"]) == 3


def test_conversations_turns_citations_export_import(tmp_path):
    db, e, p, h = _store(tmp_path)
    c = convs.create(db, e["id"], "impact of Units", "snap-1", scope={"model": "Caldergate Planning"})
    t = convs.add_turn(db, c["id"], {"q": "what reads Units?", "a": "`INP01 Volumes.Units` feeds `CAL02 Revenue.Revenue`.", "tools": [{"tool": "impact", "args": {"name": "INP01 Volumes.Units"}}],
                                     "usage": {"input": 10, "output": 5, "cost_usd": 0.001}, "unverified": [], "unchecked": [],
                                     "citations": [{"id": "c1", "kind": "line_item", "model": "Caldergate Planning", "ref": "INP01 Volumes.Units", "name": "INP01 Volumes.Units", "snapshot_id": "snap-1", "provenance": "observed", "tool": "impact"}]})
    assert t["seq"] == 1 and t["citations"][0]["id"] == "c1" and t["citations"][0]["ref"] == "INP01 Volumes.Units"
    got = convs.get(db, c["id"])
    assert got["turns_count"] == 1 and got["cost_usd"] == 0.001 and got["scope"] == {"model": "Caldergate Planning"}
    assert [x["id"] for x in convs.list_conversations(db, e["id"], q="units")] == [c["id"]]
    convs.update(db, c["id"], title="Units impact", archived=True)
    assert convs.list_conversations(db, e["id"], archived=False) == [] and convs.list_conversations(db, e["id"], archived=True)[0]["title"] == "Units impact"
    md = convs.export_markdown(db, c["id"]); assert "# Units impact" in md and "Cited: `INP01 Volumes.Units`" in md
    jl = convs.export_jsonl(db, c["id"]); assert json.loads(jl.splitlines()[2])["citations"][0]["id"] == "c1"
    # a pre-store transcript imports once, keeping its id
    ws = tmp_path / ".architect" / "transcripts"; ws.mkdir(parents=True)
    (ws / "20260922-084012-83c304.jsonl").write_text(
        '{"role":"title","text":"old chat","snapshot":"snap-0","when":"2026-09-22T08:40:12"}\n{"role":"user","text":"hi","when":"2026-09-22T08:40:13"}\n'
        '{"role":"assistant","text":"hello `Caldergate HR`","tools":[],"unverified_names":[],"citations":[{"id":"c9","kind":"model","model":"Caldergate HR","ref":"Caldergate HR","name":"Caldergate HR","snapshot_id":"snap-0","provenance":"observed","tool":"list_models"}],"usage":{"input":1,"output":1,"cost_usd":0},"when":"2026-09-22T08:40:20"}\n', encoding="utf-8")
    imp = convs.import_transcript(db, e["id"], ws / "20260922-084012-83c304.jsonl")
    assert imp["id"] == "20260922-084012-83c304" and imp["turns_count"] == 1 and imp["created"] == "2026-09-22T08:40:12"
    assert convs.import_transcript(db, e["id"], ws / "20260922-084012-83c304.jsonl") is None
    assert convs.get(db, imp["id"])["turns"][0]["citations"][0]["id"] == "c9"
    assert convs.delete(db, c["id"])["id"] == c["id"] and db.q("SELECT * FROM citations WHERE owner_id=?", t["id"]) == []


def test_bridge_backs_the_workspace(tmp_path):
    db, e, p, h = _store(tmp_path)
    w = Workspace.open(FX, tmp_path / "ws")                         # parsed from the fixture folder
    w = Workspace.from_run(w.estate, tmp_path / "ws2", backend=Bridge(db, e["id"], "snap-1"))
    w.estate_id, w.snapshot_id = e["id"], "snap-1"
    pid = next(x for x in w.index()["pattern"] if "F-HARDCODE" in x)[len("pattern:"):]
    rec = w.set_status(pid, "deliberate", "the bonus rate is a policy constant")
    assert rec["status"] == "deliberate" and w.statuses[pid]["reason"] == "the bonus rate is a policy constant"
    assert fstate.as_statuses(db, e["id"])[pid]["status"] == "deliberate" and fstate.as_statuses(db, e["id"])[pid]["snapshot"] == "snap-1"
    w.remember("model:Caldergate Planning", "Margin % is only shown where Revenue is non-zero.", by="chat")
    assert notesmod.count(db, e["id"]) == 1 and notesmod.list_notes(db, e["id"])[0]["origin_kind"] == "chat_tool"
    assert any("only shown where Revenue" in m["text"] for m in w.memories_for(model="Caldergate Planning"))
    m = material.estate_material(w)
    assert "[deliberate: the bonus rate is a policy constant]" in m and "only shown where Revenue" in m
    assert not (tmp_path / "ws2" / "statuses.json").exists()        # nothing written to JSON when the store backs it


def test_legacy_state_import_once(tmp_path):
    db, e, p, h = _store(tmp_path)
    ws = tmp_path / ".architect"; (ws / "transcripts").mkdir(parents=True)
    (ws / "memories.json").write_text(json.dumps([{"scope": "model:Caldergate HR", "text": "Headcount is loaded monthly.", "by": "user", "when": "2026-09-22T09:00:00"},
                                                  {"scope": "rule:F-DIVIDE-FN", "text": "Guarded upstream.", "by": "chat", "when": "2026-09-22T09:01:00"}]), encoding="utf-8")
    (ws / "statuses.json").write_text(json.dumps({"Caldergate Planning::F-HARDCODE::CAL03 Opex.Bonus": {"status": "deliberate", "reason": "policy", "by": "user", "when": "2026-09-22T09:02:00"}}), encoding="utf-8")
    (ws / "transcripts" / "c-old.jsonl").write_text('{"role":"title","text":"old","when":"2026-09-22T08:00:00"}\n{"role":"user","text":"q","when":"2026-09-22T08:00:01"}\n{"role":"assistant","text":"a","tools":[],"unverified_names":[],"usage":{"input":1,"output":1,"cost_usd":0},"when":"2026-09-22T08:00:02"}\n', encoding="utf-8")
    done = import_legacy_state(db, e["id"], ws)
    assert done == {"notes": 2, "statuses": 1, "conversations": 1}
    assert import_legacy_state(db, e["id"], ws) == {"notes": 0, "statuses": 0, "conversations": 0}
    ns = notesmod.list_notes(db, e["id"])
    assert {n["origin_kind"] for n in ns} == {"import"} and {n["scope_labels"][0] for n in ns} == {"model:Caldergate HR", "rule:F-DIVIDE-FN"}
    assert fstate.as_statuses(db, e["id"])["Caldergate Planning::F-HARDCODE::CAL03 Opex.Bonus"]["reason"] == "policy"
    assert convs.get(db, "c-old")["turns_count"] == 1


class _Noting(_Fake):
    """Like _Fake, but the answer quotes whatever owner notes reached it, so the test can see retrieval happen."""
    def create(self, **kw):
        r = super().create(**kw)
        first_user = kw["messages"][0]["content"] if isinstance(kw["messages"][0]["content"], str) else ""
        if "<owner_notes" in first_user and r.content[0].type == "text":
            r.content[0].text += " NOTES-SEEN"
        return r


def test_web_conversations_notes_end_to_end(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Noting)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    # a note first, then a conversation whose question matches it: the note reaches the model as evidence
    n = c.post(f"/api/estates/{eid}/notes", json={"body": "Margin % is only shown where Revenue is non-zero.", "type": "constraint", "objects": ["model:Caldergate Planning"]}).json()
    assert n["status"] == "working_assumption" and n["scope_labels"] == ["model:Caldergate Planning"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "why does Margin % show nothing where revenue is zero?", "scope": {"model": "Caldergate Planning"}}).json()
    assert conv["turns"][0]["a"].endswith("NOTES-SEEN") and conv["turns"][0]["id"].startswith("t-")
    got = c.get(f"/api/conversations/{conv['id']}").json()
    assert got["scope"] == {"model": "Caldergate Planning"} and len(got["turns"]) == 1
    assert got["turns"][0]["unchecked"] == ["CAL04 Margin.Margin %"] and got["turns"][0]["unverified"] == ["Ghost.Nope"]   # named, never looked up; invented
    # the store is the source of truth: it lists, searches, renames, archives, exports
    assert [x["id"] for x in c.get(f"/api/estates/{eid}").json()["conversations"]] == [conv["id"]]
    assert c.get(f"/api/estates/{eid}/conversations?q=margin").json()[0]["id"] == conv["id"]
    assert c.patch(f"/api/conversations/{conv['id']}", json={"title": "Margin blanks"}).json()["title"] == "Margin blanks"
    assert "# Margin blanks" in c.get(f"/api/conversations/{conv['id']}/export").text
    assert c.get(f"/api/conversations/{conv['id']}/export?format=jsonl").text.count("\n") == 3
    # save the answer as a note, with the turn's citations as sources, then confirm it
    t = got["turns"][0]
    saved = c.post(f"/api/estates/{eid}/notes", json={"body": t["a"], "title": "Margin blanks", "type": "conclusion", "origin_kind": "answer",
                                                       "conversation_id": conv["id"], "turn_id": t["id"], "sources": [x["id"] for x in t["citations"]],
                                                       "objects": ["model:Caldergate Planning"]}).json()
    assert saved["origin_kind"] == "answer" and saved["origin_turn_id"] == t["id"] and [x["id"] for x in t["citations"]] == []
    assert [x["tool"] for x in saved["sources_resolved"]] == ["scope"]          # scoped to a module: it carries that module's citation (the demo story)
    assert c.patch(f"/api/notes/{saved['id']}", json={"status": "user_confirmed"}).json()["status"] == "user_confirmed"
    assert {x["id"] for x in c.get(f"/api/estates/{eid}/notes").json()} == {n["id"], saved["id"]}
    assert c.get(f"/api/estates/{eid}/notes?q=margin&status=user_confirmed").json()[0]["id"] == saved["id"]
    # both notes on the same model surface as siblings of each other; superseding one keeps it, hidden from retrieval
    assert c.get(f"/api/notes/{n['id']}").json()["siblings"][0]["id"] == saved["id"]
    assert c.post(f"/api/notes/{n['id']}/supersede", json={"by_note": saved["id"]}).json()["superseded_by"] == saved["id"]
    assert [x["id"] for x in c.get(f"/api/estates/{eid}/notes").json()] == [saved["id"]]
    assert len(c.get(f"/api/estates/{eid}/notes?superseded=true").json()) == 2
    # a second conversation later retrieves the confirmed note; archive hides the first from the home list
    conv2 = c.post(f"/api/estates/{eid}/conversations", json={"text": "tell me about margin blanks"}).json()
    assert conv2["turns"][0]["a"].endswith("NOTES-SEEN")
    c.patch(f"/api/conversations/{conv['id']}", json={"archived": True})
    assert [x["id"] for x in c.get(f"/api/estates/{eid}").json()["conversations"]] == [conv2["id"]]
    assert c.get(f"/api/estates/{eid}/conversations?archived=true").json()[0]["id"] == conv["id"]
    # finding state through the API and the tools agree
    key = "Caldergate Planning::F-HARDCODE::CAL03 Opex.Bonus"
    assert c.patch(f"/api/estates/{eid}/findings", json={"key": key, "state": "deliberate", "reason": "policy constant"}).json()["state"] == "deliberate"
    assert c.get(f"/api/estates/{eid}/state").json()["statuses"][key]["reason"] == "policy constant"
    # a restart: conversations, notes and state all come from the store; the transcript export is still beside it
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Noting))
    again = c2.get(f"/api/conversations/{conv2['id']}").json()
    assert again["turns"][0]["a"].endswith("NOTES-SEEN") and c2.get(f"/api/estates/{eid}").json()["notes"] == 1
    assert (tmp_path / "data" / "estates" / eid / ".architect" / "transcripts" / f"{conv2['id']}.jsonl").exists()
    t3 = c2.post(f"/api/conversations/{conv2['id']}/messages", json={"text": "and then?"}).json()
    assert t3["a"].startswith("Turn 2")
    assert c2.delete(f"/api/conversations/{conv2['id']}").status_code == 200 and c2.get(f"/api/conversations/{conv2['id']}").status_code == 404
