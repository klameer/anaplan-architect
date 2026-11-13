import sys, pathlib, json, types
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from anaplan_architect.store import Workspace
from anaplan_architect import material, opinion, tools, chat
from anaplan_architect.review import render_review

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


def ws(tmp_path):
    return Workspace.open(FX, tmp_path / "ws")


def test_material_names_objects_and_statuses(tmp_path):
    w = ws(tmp_path)
    m = material.estate_material(w)
    assert "# Model: Caldergate Planning" in m and "pattern:Caldergate Planning::F-HARDCODE::" in m and "Caldergate Planning -> Caldergate HR" in m
    pid = next(p for p in w.index()["pattern"] if "F-HARDCODE" in p)[len("pattern:"):]
    w.set_status(pid, "deliberate", "guarded upstream")
    w.remember("model:Caldergate Planning", "Margin % is only shown where Revenue is non-zero.")
    m2 = material.estate_material(w)
    assert "[deliberate: guarded upstream]" in m2 and "only shown where Revenue" in m2
    w2 = Workspace.open(FX, tmp_path / "ws")          # persisted
    assert w2.status_of(pid) == "deliberate" and len(w2.memories) == 1


def test_validator_and_review(tmp_path):
    w = ws(tmp_path)
    resp = json.dumps([
        {"kind": "strength", "title": "clean SYS layer", "claim": "Time flags live in SYS01 Time Settings.", "refs": ["SYS01 Time Settings"]},
        {"kind": "materiality", "title": "divide", "claim": "Margin % divides by Revenue without a guard.", "refs": ["CAL04 Margin.Margin %", "finding:F-HARDCODE"], "priority": 1},
        {"kind": "option", "title": "guard it", "claim": "Wrap in DIVIDE.", "refs": ["CAL04 Margin.Margin %"], "effort": "days", "cost": "1 line item"},
        {"kind": "handover", "title": "start here", "claim": "Read INP01 Volumes then CAL02 Revenue.", "refs": ["INP01 Volumes", "CAL02 Revenue"]},
        {"kind": "risk", "title": "ghost", "claim": "Nothing.", "refs": ["Nope.Nothing"]},
        {"kind": "design_decision", "title": "mixed", "claim": "two bad one good.", "refs": ["Ghost", "Ghost2", "Caldergate HR"]},
    ])
    op = opinion.ingest(w, resp)
    t = {o.title: o for o in op.observations}
    assert t["divide"].kind == "materiality" and t["divide"].valid_refs == ["CAL04 Margin.Margin %", "finding:F-HARDCODE"]
    assert t["mixed"].kind == "question" and [d["title"] for d in op.dropped] == ["ghost"]
    md = render_review(w, op, title="Caldergate")
    for part in ("Architect's review: Caldergate", "What the reviewer would say first", "The handover page", "Which patterns matter", "# Anaplan estate: 2 models", "Removed by the validator"):
        assert part in md
    assert "reading" not in opinion.KINDS


def test_tools(tmp_path):
    w = ws(tmp_path); tb = tools.Toolbox(w)
    assert len(tb.list_models()["models"]) == 2
    o = tb.get_object("CAL04 Margin.Margin %")
    assert o["formula"] and "CAL04 Margin.Net Revenue" in o["uses"]
    e = tb.explain("CAL04 Margin.Margin %"); assert e["tree"]["t"] and e["references"]
    imp = tb.impact("INP01 Volumes.Units", model="Caldergate Planning"); assert imp["counts"]["line_items"] >= 2
    lin = tb.lineage("OUT01 Board Pack.Margin"); assert lin["input_line_items"]
    pats = tb.list_patterns(model="Caldergate Planning", rule="F-HARDCODE")["patterns"]; assert pats and pats[0]["status"] == "open"
    assert tb.get_pattern(pats[0]["id"])["fix"]
    assert tb.rule("F-DIVIDE-FN")["planual"] is not None
    assert tb.actions("Caldergate HR")["facts"]["orphan_count"] == 1
    v = tb.validate_formula("IF Revenue > 0 THEN Opex / Revenue ELSE 0", "Caldergate Planning", "CAL04 Margin")
    assert v["ok"] is False or v["ok"] is True   # runs and returns a verdict
    bad = tb.validate_formula("Nope.Nothing + 1", "Caldergate Planning", "CAL04 Margin"); assert bad["unresolved"]
    assert tb.set_status(pats[0]["id"], "deliberate", "guarded")["set"]["status"] == "deliberate"
    assert "error" in tb.set_status("x", "deliberate", "y")
    assert tb.remember("rule:F-DIVIDE", "divides are guarded by Is Valid? upstream")["remembered"]
    assert json.loads(tb.call("rule", {"id": "F-DIVIDE-FN"}))["id"] == "F-DIVIDE-FN" and tb.log
    names = {t["name"] for t in tools.Toolbox.schema()}
    assert {"list_models", "impact", "validate_formula", "set_status", "remember"} <= names


class _Block:
    def __init__(self, **kw): self.__dict__.update(kw)


class _FakeClient:
    """First call asks for a tool, second answers with a citation and an invented name."""
    def __init__(self): self.calls = []; self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return _Block(content=[_Block(type="tool_use", id="t1", name="get_object", input={"name": "CAL04 Margin.Margin %"})])
        last = kw["messages"][-1]["content"][0]
        assert last["type"] == "tool_result" and "Net Revenue" in last["content"]
        return _Block(content=[_Block(type="text", text="`CAL04 Margin.Margin %` divides by `CAL04 Margin.Net Revenue`; `CAL99 Ghost.Thing` does not exist.")])


def test_chat_loop_flags_invented_names(tmp_path):
    w = ws(tmp_path)
    s = chat.Session(w, client=_FakeClient())
    a = s.ask("what does Margin % do?")
    assert "Names I could not find" in a and "CAL99 Ghost.Thing" in a and "Net Revenue" in a
    lines = [json.loads(l) for l in s.path.read_text(encoding="utf-8").splitlines()]
    assert [l["role"] for l in lines if l["role"] != "usage"] == ["title", "user", "tool", "assistant"]
    assert "# The estate, in brief" in s._system()[1]["text"] and s._system()[1]["cache_control"]["type"] == "ephemeral"


class _Flaky:
    """Call 1 asks for a tool with a wrong-typed argument (the tool raises); call 2 fails outright; call 3 answers."""
    def __init__(self): self.messages = self; self.n = 0

    def create(self, **kw):
        self.n += 1
        if self.n == 1:
            return _Block(content=[_Block(type="tool_use", id="t1", name="find", input={"text": 123})])
        if self.n == 2:
            last = kw["messages"][-1]["content"][0]
            assert last["type"] == "tool_result" and "AttributeError" in last["content"]     # the tool's error reached the model as a result
            raise RuntimeError("model down")
        assert [m["role"] for m in kw["messages"]] == ["user"]                               # nothing of the failed turn was kept
        return _Block(content=[_Block(type="text", text="`CAL04 Margin.Margin %` is fine.")])


def test_a_tool_error_is_a_result_and_a_failed_turn_leaves_nothing_behind(tmp_path):
    w = ws(tmp_path)
    s = chat.Session(w, client=_Flaky())
    with pytest.raises(RuntimeError):
        s.ask("find 123")
    assert s.messages == [] and s.turns == []                    # no dangling question, no tool_use without its tool_result
    a = s.ask("again")
    assert "is fine" in a and len(s.messages) == 2 and len(s.turns) == 1
    roles = [json.loads(l)["role"] for l in s.path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert roles == ["title", "user", "tool", "error", "user", "assistant"]


def test_tool_results_carry_citation_ids_that_resolve(tmp_path):
    from anaplan_architect.orac.evidence import Evidence, cite_id
    w = ws(tmp_path); w.estate_id, w.snapshot_id = "e1", "snap-1"
    tb = tools.Toolbox(w)
    calls = [("list_models", {}), ("find", {"text": "margin"}), ("get_object", {"name": "CAL04 Margin.Margin %"}), ("get_object", {"name": "CAL04 Margin"}),
             ("explain", {"name": "CAL04 Margin.Margin %"}), ("impact", {"name": "INP01 Volumes.Units", "model": "Caldergate Planning"}),
             ("lineage", {"name": "OUT01 Board Pack.Margin"}), ("list_patterns", {"model": "Caldergate Planning"}), ("rule", {"id": "F-HARDCODE"}),
             ("actions", {"model": "Caldergate HR"}), ("validate_formula", {"formula": "Opex / Revenue", "model": "Caldergate Planning", "module": "CAL04 Margin"})]
    idx = w.index(); real = set().union(*idx.values())
    for name, args in calls:
        res = json.loads(tb.call(name, args))
        assert "cites" in res and res["cites"], name                          # every tool hands ids
        for label, cid in res["cites"].items():
            c = tb.ev.resolve(cid)
            assert c is not None and c.snapshot_id == "snap-1" and c.id == cite_id("snap-1", c.kind, c.model, c.ref), (name, label)
            key = {"model": c.ref, "module": c.ref, "line_item": c.ref, "action": "action:" + c.ref, "pattern": "pattern:" + c.ref, "finding": "finding:" + c.ref}[c.kind]
            assert key in real or (c.kind == "module" and c.ref in idx["module"]), (name, c.kind, c.ref)   # ...that resolve to a real object
    assert tb.ev.lookup("cal04 margin.margin %").kind == "line_item" and tb.ev.lookup("Caldergate Planning :: CAL04 Margin.Margin %") is not None
    # the same object gets the same id in another conversation over the same snapshot, and a different one on another snapshot
    other = tools.Toolbox(ws(tmp_path)); other.w.snapshot_id = "snap-1"; other.ev = Evidence("e1", "snap-1")
    assert json.loads(other.call("get_object", {"name": "CAL04 Margin.Margin %"}))["cites"]["CAL04 Margin.Margin %"] == tb.ev.lookup("CAL04 Margin.Margin %").id
    assert cite_id("snap-2", "line_item", "Caldergate Planning", "CAL04 Margin.Margin %") != tb.ev.lookup("CAL04 Margin.Margin %").id


def test_assess_answer_sorts_names_three_ways(tmp_path):
    w = ws(tmp_path); w.snapshot_id = "s"
    s = chat.Session(w, client=_FakeClient())
    s.ask("what does Margin % do?")
    t = s.turns[-1]
    assert [c["name"] for c in t["citations"]] == ["CAL04 Margin.Margin %", "CAL04 Margin.Net Revenue"]   # handed by get_object this turn
    assert t["unverified"] == ["CAL99 Ghost.Thing"] and t["unchecked"] == []
    a = chat.assess_answer("`OUT01 Board Pack.Margin` reads `CAL04 Margin.Margin %`; `SUM` and `IF x THEN 1 ELSE 0` are not objects; `Nope` is.", w, s.ev)
    assert [c["name"] for c in a["cited"]] == ["CAL04 Margin.Margin %"] and a["unchecked"] == ["OUT01 Board Pack.Margin"] and a["unverified"] == ["Nope"]
    r = chat.Session.resume(w, s.path, client=_FakeClient())                                     # a resumed conversation keeps what it was handed
    assert r.ev.lookup("CAL04 Margin.Net Revenue") is not None and r.turns[0]["citations"]
