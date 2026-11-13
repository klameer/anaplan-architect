"""Orac stage 5: freshness, backup and restore, deletion. A model is updated mid-history: old conversations resolve against
their original snapshot; a stale conversation asks before it answers (continue on the held snapshot, or re-evaluate on the
current one as a linked branch); notes are flagged when a cited formula changes or an object disappears; a backup leaves
credentials behind and restores under the same ids; deletion removes material from retrieval as well as the interface."""
import sys, pathlib, json, zipfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import notes as notesmod
from anaplan_architect import cli
from test_web import _B, _upload, FX, settled

PLAN_LI = FX / "1 Caldergate Planning" / "Line Items.csv"


def _v2_line_items() -> bytes:
    """The Planning export a month later: Margin % is now a percentage, and the board pack no longer shows Margin."""
    t = PLAN_LI.read_text(encoding="utf-8")
    t2 = t.replace('",Margin / Net Revenue,,Segments', '",Margin / Net Revenue * 100,,Segments')
    assert t2 != t
    lines = t2.rstrip("\n").split("\n")
    assert lines[-1].startswith("Margin,") and lines[-1].endswith("OUT01 Board Pack")
    return ("\n".join(lines[:-1]) + "\n").encode("utf-8")


def _is_tool_result(m) -> bool:
    c = m["content"]
    return isinstance(c, list) and bool(c) and isinstance(c[0], dict) and c[0].get("type") == "tool_result"


class _Cites:
    """Looks up three line items in turn (one get_object per model call), then answers naming all three."""
    NAMES = ["CAL04 Margin.Margin %", "OUT01 Board Pack.Margin", "CAL04 Margin.Margin"]

    def __init__(self): self.messages = self; self.n = 0

    def create(self, **kw):
        self.n += 1
        usage = _B(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        msgs = kw["messages"]
        i = max(j for j, m in enumerate(msgs) if m["role"] == "user" and not _is_tool_result(m))
        done = sum(1 for m in msgs[i:] if m["role"] == "user" and _is_tool_result(m))
        if done < len(self.NAMES):
            return _B(content=[_B(type="tool_use", id=f"t{self.n}", name="get_object", input={"name": self.NAMES[done]})], usage=usage)
        q = msgs[i]["content"]
        q = q if isinstance(q, str) else " ".join(b.get("text", "") for b in q if isinstance(b, dict))
        text = "Answer to: " + q.split("\n")[0][:60] + ". " + " ".join(f"`{n}`" for n in self.NAMES) + " were read."
        return _B(content=[_B(type="text", text=text)], usage=usage)


def _second_snapshot(app, c, eid: str, label: str = "v2") -> dict:
    """Planning re-exported: a draft that inherits the other three files, processed, activated. Returns the activation response."""
    s = c.get(f"/api/estates/{eid}").json()
    planning = next(m for m in s["models"] if m["name"] == "Caldergate Planning")
    r = c.post(f"/api/estates/{eid}/snapshots", data={"label": label, "model_ids": [planning["id"]]},
               files=[("line_items", ("Line Items.csv", _v2_line_items(), "text/csv"))])
    assert r.status_code == 200, r.text
    snap = r.json(); sid = snap["id"]
    assert snap["ready"] == [] and len(snap["files"]) == 4
    assert c.post(f"/api/snapshots/{sid}/process").status_code == 200
    app.state.jobs.wait(sid)
    assert c.get(f"/api/snapshots/{sid}").json()["run"]["status"] == "ok"
    r = c.post(f"/api/snapshots/{sid}/activate")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["snapshot"]["id"] == sid and "review" in out
    return out


def _cited(turn: dict) -> dict:
    return {x["ref"]: x for x in turn["citations"]}


def test_stale_conversation_continues_on_its_snapshot_or_branches(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Cites)
    c = TestClient(app)
    s1 = _upload(c).json(); eid = s1["id"]; sid1 = s1["snapshot"]["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "what does Margin % do?"}).json(); cid = conv["id"]
    c.post(f"/api/conversations/{cid}/messages", json={"text": "and the board pack?"})
    got = c.get(f"/api/conversations/{cid}").json()
    assert got["stale"] is None and len(got["turns"]) == 2 and got["branches"] == [] and got["origin"] is None
    margin = _cited(got["turns"][0])["CAL04 Margin.Margin %"]
    assert margin["snapshot_id"] == sid1
    # the estate moves on: Planning re-exported with Margin % changed and the board pack's Margin gone
    act = _second_snapshot(app, c, eid); sid2 = act["snapshot"]["id"]
    assert sid2 != sid1 and act["review"]["reviewed"] == 0
    # the old citation still opens on its own snapshot, and says what the object is now
    r = c.get(f"/api/citations/{margin['id']}").json()
    assert r["snapshot"]["id"] == sid1 and r["current"] is False and r["object"]["formula"] == "Margin / Net Revenue"
    assert r["now"]["found"] and r["now"]["changed"] and r["now"]["formula"] == "Margin / Net Revenue * 100" and r["now"]["snapshot_id"] == sid2
    gone = _cited(got["turns"][0])["OUT01 Board Pack.Margin"]
    assert c.get(f"/api/citations/{gone['id']}").json()["now"] == {"snapshot_id": sid2, "found": False, "id": None, "formula": None, "changed": False}
    # reopening: stale, and not answered until the owner chooses
    st = c.get(f"/api/conversations/{cid}").json()["stale"]
    assert st["held_on"] == sid1 and st["active"] == sid2 and st["acked"] is False and st["can_continue"] is True and st["held"]["status"] == "superseded"
    r = c.post(f"/api/conversations/{cid}/messages", json={"text": "still?"})
    assert r.status_code == 409 and r.json()["detail"]["stale"]["held_on"] == sid1 and "branch" in r.json()["detail"]["message"]
    assert c.post(f"/api/conversations/{cid}/stream", json={"text": "still?"}).status_code == 409
    assert cid not in app.state.sessions
    # continue on the held snapshot: answers are read from snapshot 1 and their citations are bound to it
    ack = c.patch(f"/api/conversations/{cid}", json={"continue_on_snapshot": True}).json()
    assert ack["stale"]["acked"] is True and ack["snapshot"] == sid1
    t3 = c.post(f"/api/conversations/{cid}/messages", json={"text": "third, on the old snapshot"}).json()
    m3 = _cited(t3)["CAL04 Margin.Margin %"]
    assert m3["snapshot_id"] == sid1 and m3["id"] == margin["id"] and "OUT01 Board Pack.Margin" in _cited(t3) and t3["unverified"] == []
    assert c.get(f"/api/citations/{m3['id']}").json()["object"]["formula"] == "Margin / Net Revenue"
    sess = app.state.sessions[cid]
    assert sess.w.snapshot_id == sid1 and sid1 in sess.context_note and sid2 in sess.context_note
    assert any(isinstance(m["content"], str) and "held on snapshot" in m["content"] for m in sess.messages)       # the model was told
    assert (eid, sid1) in app.state.workspaces and (eid, sid2) in app.state.workspaces                          # two workspaces, never mixed
    # re-evaluate on the current snapshot as a linked branch: same questions, nothing else carried over
    b = c.post(f"/api/conversations/{cid}/branch", json={}).json()
    assert b["branched_from"] == cid and b["snapshot"] == sid2 and b["held_on"] == sid1
    assert b["questions"] == ["what does Margin % do?", "and the board pack?", "third, on the old snapshot"]
    bc = c.get(f"/api/conversations/{b['id']}").json()
    assert bc["stale"] is None and bc["origin"] == {"id": cid, "title": got["title"], "snapshot_id": sid1} and bc["turns"] == [] and bc["snapshot"] == sid2
    assert [x["id"] for x in c.get(f"/api/conversations/{cid}").json()["branches"]] == [b["id"]]
    t = c.post(f"/api/conversations/{b['id']}/messages", json={"text": b["questions"][0]}).json()
    mb = _cited(t)["CAL04 Margin.Margin %"]
    assert mb["snapshot_id"] == sid2 and mb["id"] != margin["id"]
    assert c.get(f"/api/citations/{mb['id']}").json()["object"]["formula"] == "Margin / Net Revenue * 100"
    assert "OUT01 Board Pack.Margin" not in _cited(t) and "OUT01 Board Pack.Margin" in t["unchecked"] + t["unverified"]   # gone from snapshot 2: no tool handed it, so it is not evidence
    assert "re-evaluates" in app.state.sessions[b["id"]].context_note
    assert f"re-evaluation of {cid}" in c.get(f"/api/conversations/{b['id']}/export").text
    # after a restart the acknowledgement holds and the link survives both ways
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Cites))
    again = c2.get(f"/api/conversations/{cid}").json()
    assert again["stale"]["acked"] is True and [x["id"] for x in again["branches"]] == [b["id"]]
    t4 = c2.post(f"/api/conversations/{cid}/messages", json={"text": "fourth"}).json()
    assert _cited(t4)["CAL04 Margin.Margin %"]["snapshot_id"] == sid1
    heads = {h["id"]: h for h in c2.get(f"/api/estates/{eid}").json()["conversations"]}
    assert heads[cid]["branches"] == 1 and heads[b["id"]]["branched_from"] == cid
    # a third activation makes the acknowledged conversation stale again: the choice is per activation
    act3 = _second_snapshot(app, c, eid, label="v3")
    assert c.get(f"/api/conversations/{cid}").json()["stale"]["acked"] is False and c.get(f"/api/conversations/{cid}").json()["stale"]["active"] == act3["snapshot"]["id"]
    assert c.get(f"/api/conversations/{b['id']}").json()["stale"]["held_on"] == sid2


def test_notes_are_flagged_when_cited_evidence_moves(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Cites)
    c = TestClient(app); db = app.state.db
    s1 = _upload(c).json(); eid = s1["id"]; sid1 = s1["snapshot"]["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "margin?"}).json(); cid = conv["id"]
    cites = {k: v["id"] for k, v in _cited(conv["turns"][0]).items()}
    n = c.post(f"/api/estates/{eid}/notes", json={"body": "Margin % is a ratio, shown as a fraction; the board pack repeats Margin.", "title": "Margin conventions",
                                                  "objects": ["Caldergate Planning::CAL04 Margin"], "sources": list(cites.values()), "conversation_id": cid, "origin_kind": "answer"}).json()
    assert n["review_flag"] is None and n["review"] is None and n["sources_missing"] == [] and len(n["sources_resolved"]) == 4     # 3 from the answer + the module it is scoped to
    ghost = c.post(f"/api/estates/{eid}/notes", json={"body": "cites nothing real", "sources": ["c0000000000"]}).json()
    assert ghost["sources_missing"] == ["c0000000000"] and ghost["sources_resolved"] == []
    plain = c.post(f"/api/estates/{eid}/notes", json={"body": "no sources at all"}).json()
    # the conversation the note came from is deleted: the note keeps its own copy of the evidence
    assert c.delete(f"/api/conversations/{cid}").status_code == 200
    n = c.get(f"/api/notes/{n['id']}").json()
    assert len(n["sources_resolved"]) == 4 and n["sources_missing"] == []
    assert c.get(f"/api/citations/{cites['CAL04 Margin.Margin %']}").json()["cited_in"]["notes"][0]["id"] == n["id"]
    # the estate moves on
    act = _second_snapshot(app, c, eid); sid2 = act["snapshot"]["id"]
    rv = act["review"]
    assert rv["reviewed"] == 2 and rv["flagged"] == 2 and {x["id"]: x["flag"] for x in rv["notes"]} == {n["id"]: "changed", ghost["id"]: "gone"}
    n = c.get(f"/api/notes/{n['id']}").json()
    assert n["review_flag"] == "changed" and n["review"]["snapshot_id"] == sid2 and n["review"]["flag"] == "changed"
    by = {x["ref"]: x for x in n["review"]["sources"]}
    assert by["CAL04 Margin.Margin %"]["status"] == "changed" and by["CAL04 Margin.Margin %"]["was"] == "Margin / Net Revenue" and by["CAL04 Margin.Margin %"]["now"] == "Margin / Net Revenue * 100"
    assert by["OUT01 Board Pack.Margin"]["status"] == "gone" and by["CAL04 Margin.Margin"]["status"] == "unchanged"
    assert "changed: CAL04 Margin.Margin %" in n["review"]["summary"] and "gone: OUT01 Board Pack.Margin" in n["review"]["summary"]
    g = c.get(f"/api/notes/{ghost['id']}").json()
    assert g["review_flag"] == "gone" and g["review"]["sources"][0]["status"] == "deleted"
    assert c.get(f"/api/notes/{plain['id']}").json()["review_flag"] is None
    assert {x["id"] for x in c.get(f"/api/estates/{eid}/notes", params={"flagged": "true"}).json()} == {n["id"], ghost["id"]}
    assert c.get(f"/api/estates/{eid}").json()["notes_flagged"] == 2
    # the flag reaches the architect with the note: in the material and in the notes handed for a question
    assert any(m["id"] == n["id"] and "under review" in m["text"] for m in notesmod.as_memories(db, eid))
    after = c.post(f"/api/estates/{eid}/conversations", json={"title": "after"}).json()
    handed = app.state.sessions[after["id"]]._with_evidence("what are the margin conventions?")[0]
    assert "<owner_notes" in handed and "flagged: evidence it cites has changed" in handed
    # reviewed: the flag clears and the snapshot reviewed against becomes the baseline
    r = c.post(f"/api/notes/{n['id']}/reviewed").json()
    assert r["review_flag"] is None and r["reviewed_snapshot_id"] == sid2 and r["reviewed_at"]
    g2 = c.patch(f"/api/notes/{ghost['id']}", json={"body": "cites nothing real, and I know"}).json()      # editing a flagged note reviews it
    assert g2["review_flag"] is None and g2["reviewed_snapshot_id"] == sid2
    # the next activation (same files again) raises nothing: the change was seen once
    act3 = _second_snapshot(app, c, eid, label="v3")
    assert act3["review"]["reviewed"] == 2 and act3["review"]["flagged"] == 0
    assert c.get(f"/api/notes/{n['id']}").json()["review_flag"] is None and c.get(f"/api/notes/{ghost['id']}").json()["review_flag"] is None
    assert c.get(f"/api/estates/{eid}").json()["notes_flagged"] == 0
    # a superseded note leaves review as it leaves retrieval
    c.post(f"/api/notes/{n['id']}/supersede", json={})
    assert _second_snapshot(app, c, eid, label="v4")["review"]["reviewed"] == 1


def test_backup_leaves_credentials_behind_and_restores_under_the_same_ids(tmp_path, capsys):
    app = create_app(tmp_path / "data", client_factory=_Cites)
    c = TestClient(app)
    s1 = _upload(c).json(); eid = s1["id"]; sid1 = s1["snapshot"]["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "margin?"}).json(); cid = conv["id"]
    cites = {k: v["id"] for k, v in _cited(conv["turns"][0]).items()}
    n = c.post(f"/api/estates/{eid}/notes", json={"body": "Margin is fine.", "sources": [cites["CAL04 Margin.Margin %"]], "objects": ["model:Caldergate Planning"]}).json()
    plan = c.get(f"/api/estates/{eid}/plan").json()
    key = plan["actions"][0]["state_key"]
    assert c.put(f"/api/estates/{eid}/plan/state", json={"key": key, "state": "investigating", "reason": "looking"}).status_code == 200
    # the archive
    r = c.get(f"/api/estates/{eid}/backup")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/zip") and ".architect.zip" in r.headers["content-disposition"]
    zpath = tmp_path / "e.zip"; zpath.write_bytes(r.content)
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        m = json.loads(z.read("manifest.json"))
        people = json.loads(z.read("people.json"))
    assert m["kind"] == "anaplan-architect-estate" and m["estate_id"] == eid and m["active_snapshot"] == sid1
    assert m["counts"]["conversations"] == 1 and m["counts"]["notes"] == 1 and m["counts"]["blobs"] == 4 and m["counts"]["finding_state"] == 1 and m["counts"]["citations"] >= 4
    assert m["excluded"] == ["users", "sessions", "invites", "settings", "audit"]
    assert not any(x.startswith("tables/users") or "sessions" in x or "invites" in x or "settings" in x or "audit" in x for x in names)
    assert sum(1 for x in names if x.startswith("blobs/")) == 4 and any(x.startswith("architect/transcripts/") for x in names)
    assert people == [] and all("email" not in p and "pw_hash" not in p for p in people)
    ins = c.post("/api/estates/restore/inspect", files={"file": ("e.zip", zpath.read_bytes(), "application/zip")}).json()
    assert ins["conflict"] == {"id": eid, "name": "Test estate"} and ins["models"] == ["Caldergate Planning", "Caldergate HR Model"] and ins["blobs_missing"] == []
    assert c.post("/api/estates/restore", files={"file": ("e.zip", zpath.read_bytes(), "application/zip")}).status_code == 409
    assert c.post("/api/estates/restore/inspect", files={"file": ("x.zip", b"not a zip", "application/zip")}).status_code == 400
    # delete, then restore under another name: same ids, same evidence, same decisions
    assert c.request("DELETE", f"/api/estates/{eid}", json={"confirm": "Test estate"}).status_code == 200
    assert c.get(f"/api/citations/{cites['CAL04 Margin.Margin %']}").status_code == 404
    r = c.post("/api/estates/restore", data={"name": "Restored"}, files={"file": ("e.zip", zpath.read_bytes(), "application/zip")})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["id"] == eid and s["name"] == "Restored" and s["snapshot"]["id"] == sid1 and [x["name"] for x in s["models"]] == ["Caldergate Planning", "Caldergate HR Model"]
    assert s["restore"]["blobs"] == 4 and s["restore"]["authors_unknown"] == 0 and s["notes"] == 1 and [x["id"] for x in s["conversations"]] == [cid]
    got = c.get(f"/api/conversations/{cid}").json()
    assert len(got["turns"]) == 1 and got["stale"] is None and len(got["turns"][0]["citations"]) == 3
    ev = c.get(f"/api/citations/{cites['CAL04 Margin.Margin %']}").json()
    assert ev["object"]["formula"] == "Margin / Net Revenue" and ev["cited_in"]["notes"][0]["id"] == n["id"] and ev["export_row"]["row"]["Formula"] == "Margin / Net Revenue"
    assert c.get(f"/api/notes/{n['id']}").json()["sources_resolved"][0]["ref"] == "CAL04 Margin.Margin %"
    assert next(a for a in c.get(f"/api/estates/{eid}/plan").json()["actions"] if a["state_key"] == key)["state"]["state"] == "investigating"
    assert c.post(f"/api/conversations/{cid}/messages", json={"text": "again"}).json()["a"].startswith("Answer")
    # the console: list, back up to a folder, restore into a fresh store; a second restore is refused
    cli.main(["backup", "--data", str(tmp_path / "data"), "--list"])
    out = capsys.readouterr().out
    assert eid in out and "Restored" in out
    cli.main(["backup", "--data", str(tmp_path / "data"), "--estate", "Restored", "--out", str(tmp_path / "bk")])
    z2 = next((tmp_path / "bk").glob("*.architect.zip"))
    assert "Restored-" in z2.name
    capsys.readouterr()
    cli.main(["restore", "--data", str(tmp_path / "fresh"), str(z2), "--inspect"])
    assert json.loads(capsys.readouterr().out)["estate_id"] == eid
    cli.main(["restore", "--data", str(tmp_path / "fresh"), str(z2)])
    c3 = TestClient(create_app(tmp_path / "fresh", client_factory=_Cites))
    assert [e["id"] for e in c3.get("/api/estates").json()] == [eid]
    settled(c3, f"/api/estates/{eid}")                                        # a store restored from the console has no parse cache: re-read in the background first
    assert c3.get(f"/api/citations/{cites['CAL04 Margin.Margin %']}").json()["object"]["formula"] == "Margin / Net Revenue"
    assert c3.get(f"/api/conversations/{cid}").json()["turns"][1]["q"] == "again"
    with pytest.raises(SystemExit):
        cli.main(["restore", "--data", str(tmp_path / "fresh"), str(z2)])


def test_deletion_removes_material_from_retrieval(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Cites)
    c = TestClient(app); db = app.state.db
    s1 = _upload(c).json(); eid = s1["id"]; sid1 = s1["snapshot"]["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "margin?"}).json(); cid = conv["id"]
    cites = {k: v["id"] for k, v in _cited(conv["turns"][0]).items()}
    n = c.post(f"/api/estates/{eid}/notes", json={"body": "Margin is guarded upstream by Is Valid?", "title": "Margin guard", "sources": [cites["CAL04 Margin.Margin %"]]}).json()
    assert [x["id"] for x in notesmod.search(db, eid, "how is margin guarded?")] == [n["id"]]
    # a deleted note leaves retrieval, the index and the material
    assert c.delete(f"/api/notes/{n['id']}").status_code == 200
    assert notesmod.search(db, eid, "how is margin guarded?") == [] and notesmod.count(db, eid) == 0
    assert db.q("SELECT * FROM citations WHERE owner_kind='note' AND owner_id=?", n["id"]) == [] and db.q("SELECT rowid FROM notes_fts WHERE notes_fts MATCH 'guarded'") == []
    assert "<owner_notes" not in app.state.sessions[cid]._with_evidence("how is margin guarded?")[0]
    # a deleted conversation takes its citations with it; ids the tools handed there no longer open
    assert c.delete(f"/api/conversations/{cid}").status_code == 200
    assert db.q("SELECT * FROM turns WHERE conversation_id=?", cid) == [] and db.q("SELECT * FROM citations WHERE owner_kind='turn'") == []
    assert c.get(f"/api/citations/{cites['CAL04 Margin.Margin %']}").status_code == 404 and cid not in app.state.sessions
    # a superseded snapshot is kept while anything points at it, and goes when nothing does
    conv2 = c.post(f"/api/estates/{eid}/conversations", json={"text": "on snapshot one"}).json()
    act = _second_snapshot(app, c, eid); sid2 = act["snapshot"]["id"]
    r = c.delete(f"/api/snapshots/{sid1}")
    assert r.status_code == 409 and "1 conversations" in r.json()["detail"] and "citations" in r.json()["detail"]
    row = next(x for x in c.get(f"/api/estates/{eid}/snapshots").json() if x["id"] == sid1)
    assert row["status"] == "superseded" and row["held_conversations"] == 1 and row["citations"] >= 3 and row["deletable"] is False
    assert c.get(f"/api/snapshots/{sid1}").json()["references"]["conversations"] == 1
    assert c.delete(f"/api/conversations/{conv2['id']}").status_code == 200
    assert c.get(f"/api/snapshots/{sid1}").json()["deletable"] is True
    blobs_before = len(db.q("SELECT * FROM blobs"))
    r = c.delete(f"/api/snapshots/{sid1}")
    assert r.status_code == 200 and r.json()["blobs_removed"] == 1 and len(db.q("SELECT * FROM blobs")) == blobs_before - 1     # the v1 Planning export, held by nothing else
    assert not (tmp_path / "data" / "estates" / eid / "snapshots" / sid1).exists() and c.get(f"/api/snapshots/{sid1}").status_code == 404
    assert c.delete(f"/api/snapshots/{sid2}").status_code == 409        # active: kept
    # deleting the estate leaves no row, folder, session, workspace, plan or citation behind
    c.post(f"/api/estates/{eid}/conversations", json={"text": "last"})
    c.get(f"/api/estates/{eid}/plan")
    c.post(f"/api/estates/{eid}/notes", json={"body": "gone soon"})
    assert sid2 in app.state.plans and any(k[0] == eid for k in app.state.workspaces) and any(s.w.estate_id == eid for s in app.state.sessions.values())
    assert c.request("DELETE", f"/api/estates/{eid}", json={"confirm": "Test estate"}).status_code == 200
    for table in ("conversations", "notes", "snapshots", "models", "proposals", "finding_state"):
        assert db.q(f"SELECT * FROM {table} WHERE estate_id=?", eid) == []
    assert db.q("SELECT * FROM citations") == [] and db.q("SELECT * FROM turns") == [] and db.q("SELECT * FROM note_sources") == [] and db.q("SELECT * FROM blobs") == []
    assert sid2 not in app.state.plans and not any(k[0] == eid for k in app.state.workspaces) and not any(s.w.estate_id == eid for s in app.state.sessions.values())
    assert not (tmp_path / "data" / "estates" / eid).exists() and c.get("/api/estates?archived=true").json() == []
