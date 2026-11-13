"""Orac stage 3: citations surfaced. The validator sorts names, ids and figures; the store keeps the verdict;
a citation id opens the object as its snapshot held it, with the export row, and says what it is now."""
import sys, pathlib, json, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from fastapi.testclient import TestClient
from anaplan_architect.orac.evidence import Evidence, cite_id, figures, note_provenance, NOTE_ID
from anaplan_architect.orac import objects as objmod
from anaplan_architect.store import Workspace
from anaplan_architect import chat, tools
from anaplan_architect.web import create_app
from test_web import _B, _upload, FX


def test_figures_guard_traces_derives_and_flags():
    src = ['{"cells": 5017824, "calc_effort_pct": 16.04, "downstream_line_items": 7, "share": 0.1604}', "# Model\n12 modules, 1,234 line items"]
    f = figures("It has 1,234 line items in 12 modules; `CAL04 Margin.Margin %` carries 16% of effort over 5.0M cells (5,017,824 exactly, 0.16 as a share). "
                "Seven of the 7 dependents sit in 3 modules.", src)
    assert f["untraced"] == [] and f["traced"] == 6 and f["benign"] == 2 and f["derived"] == 0
    g = figures("The other 42 items and 99.9% of the rest are made up.", src)
    assert g["untraced"] == ["42", "99.9%"] and g["checked"] == 2
    d = figures("1,234 + 12 = 1,246 line items and modules together; 12 of 1,234 is 0.97%.", src)
    assert d["untraced"] == [] and d["derived"] == 2 and d["traced"] == 4
    assert figures("`c1234abcd00` has 314159 cells; see `n-0123456789`.", ["cells: 1"])["untraced"] == ["314159"]     # code spans are not figures
    assert figures("Step 3 of 10 in 2026 at 06:00; 12 of them, v0.1.0, CAL04, 2026-09-25.", [])["untraced"] == ["12"]  # names, dates, times, versions
    assert figures("10.9bn cells and 2.3M more, minus 12%", ["10900000000 2300000 -12"])["untraced"] == []


def test_assess_answer_sorts_names_ids_and_notes(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws"); w.snapshot_id = "s1"
    ev = Evidence("e", "s1")
    tb = tools.Toolbox(w, ev)
    cid = json.loads(tb.call("get_object", {"name": "CAL04 Margin.Margin %"}))["cites"]["CAL04 Margin.Margin %"]
    ev.mint("note", "", "n-0123456789", "Revenue timing", tool="notes", provenance="user_confirmed")
    a = chat.assess_answer(f"See {cid} and `n-0123456789`; also `c0000000000` and n-ffffffffff were never handed. "
                           f"`CAL04 Margin.Net Revenue` was handed too, `OUT01 Board Pack.Margin` was not, `Nope.Nothing` does not exist.", w, ev)
    ids = {c["id"]: c for c in a["cited"]}
    assert cid in ids and ids[cid]["as_written"] == cid and ids[cid]["kind"] == "line_item"
    assert any(c["kind"] == "note" and c["provenance"] == "user_confirmed" and c["ref"] == "n-0123456789" for c in a["cited"])
    assert any(c["ref"] == "CAL04 Margin.Net Revenue" for c in a["cited"])
    assert a["phantom"] == ["c0000000000", "n-ffffffffff"] and a["unchecked"] == ["OUT01 Board Pack.Margin"] and a["unverified"] == ["Nope.Nothing"]
    v = chat.verification_of(a, figures("nothing numeric", []))
    assert v["mode"] == "checked" and v["cited"] == 3 and v["clean"] is False
    assert note_provenance({"status": "working_assumption", "origin_kind": "answer"}) == "ai_proposed"
    assert note_provenance({"status": "working_assumption", "origin_kind": "user"}) == "not_established"
    # a one-character code span must not make the scan jump between backticks (seen live: `0` produced names like `. It carries`)
    b = chat.assess_answer("`CAL04 Margin.Margin %` returns `0` for actuals.\n\nDownstream it is read by `OUT01 Board Pack.Margin`.\n\nIt carries `0` cells and `%`.", w, ev)
    assert b["unverified"] == [] and b["unchecked"] == ["OUT01 Board Pack.Margin"] and [c["ref"] for c in b["cited"]] == ["CAL04 Margin.Margin %"]


def test_guess_and_resolve_over_the_fixture(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    er = w.estate
    assert objmod.guess(er, "CAL04 Margin.Margin %") == ("line_item", "Caldergate Planning", "CAL04 Margin.Margin %")
    assert objmod.guess(er, "margin %") == ("line_item", "Caldergate Planning", "CAL04 Margin.Margin %")        # unique bare name
    assert objmod.guess(er, "cal04 margin")[:2] == ("module", "Caldergate Planning")
    assert objmod.guess(er, "Caldergate HR")[0] == "model" and objmod.guess(er, "F-HARDCODE")[0] == "finding"
    assert objmod.guess(er, "Load Actuals", "Caldergate Planning") == ("action", "Caldergate Planning", "Load Actuals")
    assert objmod.guess(er, "Nothing.Here")[0] is None
    li = objmod.resolve(er, "line_item", "Caldergate Planning", "CAL04 Margin.Margin %", "snap-1")
    assert li["formula"] == "Margin / Net Revenue" and [u["ref"] for u in li["uses"]] == ["CAL04 Margin.Margin", "CAL04 Margin.Net Revenue"]
    assert li["id"] == cite_id("snap-1", "line_item", "Caldergate Planning", "CAL04 Margin.Margin %") and li["module_id"] == cite_id("snap-1", "module", "Caldergate Planning", "CAL04 Margin")
    assert li["references"][0]["kind"] == "line_item" and li["used_by_count"] == 0
    mod = objmod.resolve(er, "module", "Caldergate Planning", "CAL04 Margin", "snap-1")
    assert mod["line_item_count"] == 6 and any(x["ref"] == "CAL03 Opex" for x in mod["uses_modules"])
    assert objmod.resolve(er, "model", None, "Caldergate Planning", "snap-1")["feeds"][0]["model"] == "Caldergate HR"
    assert objmod.resolve(er, "line_item", "Caldergate Planning", "Nope.Nothing", "snap-1") is None


class _Citing:
    """Looks up Margin %, then answers citing it and two neighbours, with one figure the tools returned and one they did not,
    and an invented name. If owner notes reached it, it cites the first one by id and one id that was never handed."""
    def __init__(self): self.messages = self; self.n = 0

    def create(self, **kw):
        self.n += 1
        last = kw["messages"][-1]
        tool_turn = isinstance(last["content"], list) and last["content"] and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result"
        usage = _B(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if not tool_turn:
            return _B(content=[_B(type="tool_use", id=f"t{self.n}", name="get_object", input={"name": "CAL04 Margin.Margin %"})], usage=usage)
        text = "`CAL04 Margin.Margin %` divides `CAL04 Margin.Margin` by `CAL04 Margin.Net Revenue` over 72 cells; it has 777 dependents. `Ghost.Nope` is invented."
        first = kw["messages"][0]["content"]
        first = first if isinstance(first, str) else " ".join(b.get("text", "") for b in first if isinstance(b, dict))
        if "<owner_notes" in first:
            nid = NOTE_ID.search(first).group(0)
            text += f" The owner said so in `{nid}`; `n-0000000000` says otherwise."
        return _B(content=[_B(type="text", text=text)], usage=usage)


def test_turn_verification_and_citation_opens_evidence(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Citing)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    conv = c.post(f"/api/estates/{eid}/conversations", json={"text": "what does Margin % do?"}).json()
    t = conv["turns"][0]; v = t["verification"]
    assert v["mode"] == "checked" and v["cited"] == 3 and v["unverified"] == 1 and v["unchecked"] == 0 and v["phantom"] == [] and v["clean"] is False
    assert v["figures"]["untraced"] == ["777"] and v["figures"]["traced"] == 1
    got = c.get(f"/api/conversations/{conv['id']}").json()["turns"][0]
    assert got["verification"] == v and {x["ref"] for x in got["citations"]} == {"CAL04 Margin.Margin %", "CAL04 Margin.Margin", "CAL04 Margin.Net Revenue"}
    md = c.get(f"/api/conversations/{conv['id']}/export").text
    assert "Checked: 3 cited" in md and "1 untraced: 777" in md
    # the citation opens the line item as the snapshot held it, with the row of the export it came from
    cid = next(x["id"] for x in got["citations"] if x["ref"] == "CAL04 Margin.Margin %")
    r = c.get(f"/api/citations/{cid}").json()
    assert r["kind"] == "line_item" and r["current"] is True and r["provenance"] == "observed" and r["tool"] == "get_object" and r["snapshot"]["status"] == "active"
    o = r["object"]
    assert o["module"] == "CAL04 Margin" and o["formula"] == "Margin / Net Revenue" and o["cells"] == 72 and [u["ref"] for u in o["uses"]] == ["CAL04 Margin.Margin", "CAL04 Margin.Net Revenue"]
    assert r["export_row"]["file"] == "Line Items.csv" and r["export_row"]["row"]["Formula"] == "Margin / Net Revenue" and r["export_row"]["row"]["Module Name"] == "CAL04 Margin"
    assert r["cited_in"]["turns"][0]["turn_id"] == t["id"] and r["now"] is None and r["looked_up_now"] is False
    # a neighbour the tools handed opens by id; one they never handed is a 404 by id and a lookup by name instead
    nb = o["uses"][0]
    assert c.get(f"/api/citations/{nb['id']}").json()["object"]["ref"] == "CAL04 Margin.Margin"
    assert c.get(f"/api/citations/{o['module_id']}").json()["kind"] == "module"       # the module came with the line item: the live session resolves it
    never = cite_id(r["snapshot"]["id"], "module", "Caldergate Planning", "CAL03 Opex")
    assert c.get(f"/api/citations/{never}").status_code == 404
    m = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL03 Opex", "model": "Caldergate Planning"}).json()
    assert m["id"] == never and m["kind"] == "module" and m["looked_up_now"] is True and m["object"]["line_item_count"] >= 2 and m["export_row"] is None
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "CAL04 Margin"}).json()["object"]["line_item_count"] == 6
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "Margin %"}).json()["id"] == cid                     # unique bare name, same id
    li2 = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL04 Margin.Margin %", "kind": "line_item"}).json()  # kind known, model not: found across models
    assert li2["id"] == cid and li2["model"] == "Caldergate Planning"
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "CAL04 Margin", "kind": "line_item"}).status_code == 404
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "SYS01 Time Settings", "kind": "module"}).json()["model"] == "Caldergate Planning"
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "Caldergate Planning"}).json()["object"]["facts"]["modules"] >= 5
    a = c.get(f"/api/estates/{eid}/object", params={"ref": "Import Actuals from NetSuite", "model": "Caldergate Planning"}).json()
    assert a["kind"] == "action" and a["object"]["target"] == "INP01 Volumes" and a["object"]["processes"][0]["ref"] == "Load Actuals"
    assert a["export_row"]["row"]["Action"] == "Import into 'INP01 Volumes'" and a["export_row"]["file"] == "Actions.csv"
    p = c.get(f"/api/estates/{eid}/object", params={"ref": "Load Actuals", "model": "Caldergate Planning"}).json()
    assert p["object"]["action_kind"] == "process" and p["object"]["last_run"] == "2026-08-01 06:00:00" and isinstance(p["object"]["steps"], list)
    rule = c.get(f"/api/estates/{eid}/object", params={"ref": "F-HARDCODE"}).json()
    assert rule["kind"] == "finding" and rule["object"]["title"] and rule["object"]["patterns"]
    pat = c.get(f"/api/estates/{eid}/object", params={"ref": rule["object"]["patterns"][0]["id"]}).json()
    assert pat["kind"] == "pattern" and pat["object"]["count"] >= 1 and pat["object"]["status"] == "open" and pat["object"]["objects"][0]["id"]
    assert c.get(f"/api/estates/{eid}/object", params={"ref": "Nothing.Here"}).status_code == 404
    assert c.get("/api/citations/c0000000000").status_code == 404
    # a note carrying the citation as a source resolves it, and is itself citable: by id on the next question, with provenance from its status
    n = c.post(f"/api/estates/{eid}/notes", json={"body": "Margin % is guarded upstream.", "title": "Margin guard", "objects": ["model:Caldergate Planning"], "sources": [cid]}).json()
    assert n["sources_resolved"][0]["ref"] == "CAL04 Margin.Margin %" and n["sources_resolved"][0]["kind"] == "line_item"
    r3 = c.get(f"/api/estates/{eid}/object", params={"ref": n["id"]}).json()
    assert r3["kind"] == "note" and r3["provenance"] == "not_established" and r3["object"]["id"] == n["id"] and r3["name"] == "Margin guard"
    assert c.get(f"/api/citations/{cid}").json()["cited_in"]["notes"][0]["id"] == n["id"]
    conv2 = c.post(f"/api/estates/{eid}/conversations", json={"text": "is margin guarded?"}).json()
    t2 = conv2["turns"][0]
    note_cite = next(x for x in t2["citations"] if x["kind"] == "note")
    assert note_cite["ref"] == n["id"] and note_cite["provenance"] == "not_established" and t2["verification"]["phantom"] == ["n-0000000000"]
    assert c.get(f"/api/citations/{note_cite['id']}").json()["object"]["id"] == n["id"]
    c.patch(f"/api/notes/{n['id']}", json={"status": "user_confirmed"})
    assert c.get(f"/api/citations/{note_cite['id']}").json()["provenance"] == "user_confirmed"                   # the note's current status wins
    # the estate moves on: Margin % changes in a new snapshot. The old citation still opens on its own snapshot and says what the object is now
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes().replace(b"Margin / Net Revenue", b"IF Net Revenue <> 0 THEN Margin / Net Revenue ELSE 0")
    mid = next(x["id"] for x in c.get(f"/api/estates/{eid}").json()["models"] if x["name"] == "Caldergate Planning")
    snap = c.post(f"/api/estates/{eid}/snapshots", data={"label": "guarded", "model_ids": [mid]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()
    assert c.post(f"/api/snapshots/{snap['id']}/process").status_code == 200
    app.state.jobs.wait(snap["id"])
    assert c.post(f"/api/snapshots/{snap['id']}/activate").status_code == 200
    r4 = c.get(f"/api/citations/{cid}").json()
    assert r4["current"] is False and r4["snapshot"]["status"] == "superseded" and r4["object"]["formula"] == "Margin / Net Revenue"
    assert r4["now"]["found"] and r4["now"]["changed"] and r4["now"]["formula"].startswith("IF Net Revenue") and r4["now"]["id"] != cid
    now = c.get(f"/api/estates/{eid}/object", params={"ref": "CAL04 Margin.Margin %"}).json()
    assert now["id"] == r4["now"]["id"] and now["current"] is True and now["export_row"]["row"]["Formula"].startswith("IF Net Revenue")
    # a restart keeps every verdict and every citation resolvable
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Citing))
    assert c2.get(f"/api/conversations/{conv['id']}").json()["turns"][0]["verification"]["figures"]["untraced"] == ["777"]
    assert c2.get(f"/api/citations/{cid}").json()["object"]["formula"] == "Margin / Net Revenue"
