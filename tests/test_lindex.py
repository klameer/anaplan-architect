"""v0.2 P2: the line-item index agrees with the engine, and a model with thousands of line items is answered with an
exact count and a few rows, never the list."""
import sys, pathlib, json, csv, io
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import lindex
from anaplan_estate import fleet

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"
HEAD = ",Format,Formula,Summary,Applies To,Time Scale,Time Range,Versions,Style,Cell Count,Notes,Referenced By,Module Name"


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "ARCHITECT_CONTEXT_BUDGET"):
        monkeypatch.delenv(k, raising=False)


class _B:
    def __init__(self, **kw): self.__dict__.update(kw)


def _upload(c, name="Idx"):
    files, names = [], []
    for d in sorted(FX.iterdir()):
        files.append(("line_items", ("Line Items.csv", (d / "Line Items.csv").read_bytes(), "text/csv")))
        files.append(("actions", ("Actions.csv", (d / "Actions.csv").read_bytes(), "text/csv")))
        names.append(d.name.split(" ", 1)[1])
    return c.post("/api/estates", data={"name": name, "model_names": names}, files=files).json()["id"]


def test_index_agrees_with_the_engine(tmp_path):
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    eid = _upload(c)
    er = fleet.run(FX)
    db = app.state.db
    uploaded = [d.name.split(" ", 1)[1] for d in sorted(FX.iterdir())]          # the names the upload gave the models, in the folder's order
    for name, m in zip(uploaded, er.models):
        items = [(k, li) for k, li in m.model.line_items.items() if not li.is_header]
        q = lambda **kw: c.get(f"/api/estates/{eid}/lineitems", params=dict(model=name, limit=0, **kw)).json()
        assert q()["count"] == len(items) == m.facts["line_items"]
        assert q(calculated="true")["count"] == sum(1 for _, li in items if li.formula) == m.facts["calculated"]
        assert q()["cells"] == sum(li.cell_count for _, li in items)
        # references: every edge of the engine's graph, once
        sid = db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)["id"]
        n_refs = db.one("SELECT COUNT(*) AS n FROM li_refs WHERE snapshot_id=? AND model=?", sid, name)["n"]
        assert n_refs == sum(len(v) for v in m.graph.edges.values())
        # what reads a line item is what the graph's reverse edges say
        hub = max(m.graph.rev, key=lambda k: len(m.graph.rev[k]))
        r = q(references=f"{hub[0]}.{hub[1]}")
        assert r["count"] == len(m.graph.rev[hub])
        # unreferenced calculated line items: the engine's own figure
        assert q(calculated="true", unreferenced="true")["count"] == sum(1 for k, li in items if li.formula and not m.graph.rev.get(k))
    # a function count is the number of formulas whose parse tree holds the call, over the whole estate
    from anaplan_grammar.parser import parse
    def uses(node, name):
        if isinstance(node, list):
            return any(uses(x, name) for x in node)
        if not isinstance(node, dict):
            return False
        return (node.get("t") == "call" and node.get("f", "").upper() == name) or (name == "IF" and node.get("t") == "if") or any(uses(v, name) for v in node.values())
    for fn in ("IF", "DIVIDE"):
        want = sum(1 for m in er.models for li in m.model.line_items.values() if li.formula and not li.is_header and uses(parse(li.formula), fn))
        got = c.get(f"/api/estates/{eid}/lineitems", params={"function": fn, "limit": 3}).json()
        assert got["count"] == want and got["rows_shown"] <= 3 and sum(got["by_model"].values()) == want
    g = c.get(f"/api/estates/{eid}/lineitems", params={"group_by": "function", "limit": 0}).json()["groups"]
    assert g["by"] == "function" and any(r["key"] == "IF" for r in g["rows"])
    assert c.get(f"/api/estates/{eid}/lineitems", params={"group_by": "nonsense"}).status_code == 400
    p = c.get(f"/api/estates/{eid}/profile", params={"model": uploaded[0]}).json()
    assert p["modules"] and p["functions"] and all(len(e) == 3 for e in p["edges"]) and p["stats"]["line_items"] == sum(m.facts["line_items"] for m in er.models)


def _big_model(modules=120, per=30) -> bytes:
    """A model of thousands of line items: `modules` store modules of `per` line items each, one FINDITEM in every tenth."""
    out = io.StringIO(); out.write(HEAD + "\n")
    w = csv.writer(out)
    for i in range(modules):
        mod = f"STR{i:03d} Store Plan"
        w.writerow([mod, "", "", "", "", "Not Applicable", "Not Applicable", "Not Applicable", "", 0, "", "", ""])
        for j in range(per):
            name = f"Line {j:02d}"
            formula = "" if j == 0 else (f"FINDITEM(Stores, 'STR{i:03d} Store Plan'.Line 00)" if j % 10 == 5 else f"'STR{i:03d} Store Plan'.Line {j - 1:02d} * 2")
            w.writerow([name, json.dumps({"dataType": "NUMBER"}), formula, "Sum" if formula else "", "Stores", "Month", "Model Calendar", "Not Applicable", "", 1200, "", "", mod])
    return out.getvalue().encode()


class Counting:
    """Asks the index once, then reports its count."""
    def __init__(self): self.messages = self; self.seen = []; self.narrow = False; self.first = None

    def create(self, **kw):
        self.seen.append(kw)
        last = kw["messages"][-1]
        usage = _B(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if isinstance(last["content"], list) and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result" and not (self.narrow and len(self.seen) == 2):
            r = json.loads(last["content"][0]["content"])
            if self.narrow:                               # the answer states the whole count, not the narrower one it looked at last
                r = self.first
            return _B(content=[_B(type="text", text=f"## Brief\n\n{r['count']} line items use FINDITEM, out of {r['of_line_items']}.")], usage=usage)
        if self.narrow and len(self.seen) == 2:            # a second, narrower look after the count: one module only
            return _B(content=[_B(type="tool_use", id="t2", name="query_line_items", input={"function": "FINDITEM", "module": "STR000 Store Plan", "limit": 5})], usage=usage)
        return _B(content=[_B(type="tool_use", id="t1", name="query_line_items", input={"function": "FINDITEM", "limit": 5})], usage=usage)


def test_thousands_of_line_items_one_exact_count_and_no_list_in_the_prompt(tmp_path):
    model = Counting()
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    c = TestClient(app)
    eid = c.post("/api/estates", data={"name": "Big", "model_names": ["Store Planning"]}, files=[("line_items", ("Line Items.csv", _big_model(), "text/csv"))]).json()["id"]
    assert c.get(f"/api/estates/{eid}").json()["models"][0]["line_items"] == 3600
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "count", "text": "How many line items use FINDITEM?"}).json()["turns"][0]
    assert t["a"].strip().endswith("360 line items use FINDITEM, out of 3600.") and t["verification"]["clean"] and t["kind"] == "count"
    blk = next(b for b in t["blocks"] if b["type"] == "count")
    assert blk["count"] == 360 and blk["of"] == 3600 and blk["by_model"] == {"Store Planning": 360} and len(blk["rows"]) == 5
    # the tool result that went to the model: a count and five rows, a few hundred tokens for 3,600 line items
    sent = model.seen[1]["messages"][-1]["content"][0]["content"]
    r = json.loads(sent)
    assert r["count"] == 360 and r["rows_shown"] == 5 and len(sent) < 4000
    item = next(i for i in t["context"]["items"] if i["label"].startswith("Line-item index"))
    assert item["tokens"] < 1000
    # two queries in one turn, the second narrower: the panel shows the count the answer states, not the last one run
    model.narrow = True; model.seen = []
    orig = model.create
    def create(**kw):
        out = orig(**kw)
        msgs = [m for m in kw["messages"] if isinstance(m["content"], list) and isinstance(m["content"][0], dict) and m["content"][0].get("type") == "tool_result"]
        if msgs and model.first is None:
            model.first = json.loads(msgs[0]["content"][0]["content"])
        return out
    model.create = create
    t2 = c.post(f"/api/estates/{eid}/conversations", json={"title": "count again", "text": "How many line items use FINDITEM?"}).json()["turns"][0]
    assert [x["tool"] for x in t2["tools"]] == ["query_line_items", "query_line_items"] and "360 line items" in t2["a"]
    assert next(b for b in t2["blocks"] if b["type"] == "count")["count"] == 360
    # asking for everything still returns at most 25 rows
    assert c.get(f"/api/estates/{eid}/lineitems", params={"limit": 5000}).json()["rows_shown"] == lindex.MAX_ROWS


def test_the_index_follows_a_model_rename_and_a_reparse(tmp_path):
    """Review 2026-11-13, item 3: the index was written once per snapshot and never again, so after a model was renamed
    a count under its new name was an exact zero."""
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    eid = _upload(c)
    s = c.get(f"/api/estates/{eid}").json()
    m = s["models"][0]; old = m["name"]
    n = c.get(f"/api/estates/{eid}/lineitems", params={"model": old, "limit": 0}).json()["count"]
    fn = c.get(f"/api/estates/{eid}/lineitems", params={"model": old, "calculated": "true", "limit": 0}).json()["count"]
    assert n > 0 and fn > 0
    assert c.patch(f"/api/models/{m['id']}", json={"name": "Renamed Planning"}).status_code == 200
    def q(**kw):
        import time
        for _ in range(100):                           # a rename re-reads the exports in the background: the page asks again, so does this
            r = c.get(f"/api/estates/{eid}/lineitems", params=dict(limit=0, **kw))
            if r.status_code != 409:
                return r.json()["count"]
            time.sleep(0.1)
        raise AssertionError("still re-reading")
    assert q(model="Renamed Planning") == n and q(model="Renamed Planning", calculated="true") == fn and q(model=old) == 0
    db = app.state.db
    sid = db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)["id"]
    assert {r["model"] for r in db.q("SELECT DISTINCT model FROM li_refs WHERE snapshot_id=?", sid)} == {r["model"] for r in db.q("SELECT DISTINCT model FROM li_index WHERE snapshot_id=?", sid)}
    # an index that no longer matches the parse (rows lost, or left by an earlier parse of the same snapshot) is rebuilt on the next read
    db.run("DELETE FROM li_index WHERE snapshot_id=? AND rowid IN (SELECT rowid FROM li_index WHERE snapshot_id=? AND model='Renamed Planning' LIMIT 3)", sid, sid)
    assert q(model="Renamed Planning") == n
    db.run("UPDATE li_index SET formula='stale', calculated=0 WHERE snapshot_id=?", sid)
    lindex.drop(db, sid)                               # what a re-parse does
    assert q(model="Renamed Planning", calculated="true") == fn


def test_every_function_a_reference_sits_in_no_double_counted_cells_and_no_wildcards(tmp_path):
    """Review 2026-11-13, item 11 (the index)."""
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    out = io.StringIO(); out.write(HEAD + "\n")
    w = csv.writer(out)
    num = json.dumps({"dataType": "NUMBER"})
    def module(name, items):
        w.writerow([name, "", "", "", "", "Not Applicable", "Not Applicable", "Not Applicable", "", 0, "", "", ""])
        for li, formula, cells in items:
            w.writerow([li, num, formula, "Sum" if formula else "", "Regions", "Month", "Model Calendar", "Not Applicable", "", cells, "", "", name])
    module("Src", [("Amount", "", 100), ("Rate_1", "", 10), ("Rate%1", "", 10)])
    module("SrcX", [("Other", "", 10)])
    module("Use", [("Twice", "IF Src.Amount > 0 THEN SUM(Src.Amount, Src.Rate_1) ELSE MAX(Src.Amount, 0)", 40),
                   ("Ifs", "IF Src.Amount > 0 THEN 1 ELSE IF Src.Amount < 0 THEN 2 ELSE 3", 60), ("FromX", "SrcX.Other", 5)])
    eid = c.post("/api/estates", data={"name": "Small", "model_names": ["M"]}, files=[("line_items", ("Line Items.csv", out.getvalue().encode(), "text/csv"))]).json()["id"]
    q = lambda **kw: c.get(f"/api/estates/{eid}/lineitems", params=dict(model="M", **kw)).json()
    assert q(limit=0)["count"] == 7
    db = app.state.db
    # every function a reference sits in is kept, not only the first
    fn = db.one("SELECT fn FROM li_refs WHERE from_ref='Use.Twice' AND to_ref='Src.Amount'")["fn"]
    assert {"SUM", "MAX"} <= set(x for x in fn.split("|") if x), fn
    # cells grouped by function: a line item's cells once per function, however many times or ways the function appears
    g = {r["key"]: r for r in q(group_by="function", limit=0)["groups"]["rows"]}
    assert g["IF"]["line_items"] == 2 and g["IF"]["cells"] == 100, g["IF"]
    # an underscore or a percent sign in a name is that character, not a wildcard
    assert q(referenced_by="Use", limit=0)["count"] == 3            # what the module Use reads: Src.Amount, Src.Rate_1, SrcX.Other
    assert q(referenced_by="Us_", limit=0)["count"] == 0 and q(referenced_by="Use%", limit=0)["count"] == 0 and q(referenced_by="U%", limit=0)["count"] == 0
    assert q(dimension="Regi_ns", limit=0)["count"] == 0 and q(dimension="Regions", limit=0)["count"] == 7
    sid = db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)["id"]
    assert q(format="N_mber", limit=0)["count"] == 0 and q(format="Number", limit=0)["count"] == 7
    assert lindex.query(db, sid, summary="S_m", limit=0)["count"] == 0 and lindex.query(db, sid, summary="Sum", limit=0)["count"] == 3
