"""v0.2 P3: a build plan is checked by code. Every formula parses, every reference resolves against the model or the
plan's own new objects, the order is proven, and a cycle or an unresolved reference rejects the plan."""
import sys, pathlib, json, csv, io
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import buildplan
from anaplan_estate import fleet

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "ARCHITECT_CONTEXT_BUDGET"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(scope="module")
def planning():
    return next(m for m in fleet.run(FX).models if "Planning" in m.name)


# An extension of the fixture model, proposed out of order on purpose: the output first, the input last.
PLAN = [
    {"name": "OUT05 Scenario Pack", "applies_to": ["Segments", "Scenarios", "Time"], "note": "What the page reads.",
     "line_items": [{"name": "Margin vs Base", "format": "Number", "summary": "Sum", "formula": "'CAL09 Scenario Margin'.Scenario Margin - 'CAL09 Scenario Margin'.Scenario Margin[SELECT: Scenarios.Base]"},
                    {"name": "Margin", "format": "Number", "summary": "Sum", "formula": "'CAL09 Scenario Margin'.Scenario Margin"}]},
    {"name": "CAL09 Scenario Margin", "applies_to": ["Segments", "Scenarios", "Time"], "note": "Margin under each scenario.",
     "line_items": [{"name": "Scenario Margin", "format": "Number", "summary": "Sum", "formula": "Scenario Revenue * 'CAL04 Margin'.Margin %"},
                    {"name": "Scenario Revenue", "format": "Number", "summary": "Sum", "formula": "'CAL02 Revenue'.Net Revenue * (1 + 'INP09 Scenario Drivers'.Revenue Flex %)"}]},
    {"name": "INP09 Scenario Drivers", "applies_to": ["Scenarios"], "note": "One flex per scenario.",
     "line_items": [{"name": "Revenue Flex %", "format": "Number", "summary": "None", "formula": ""}]},
]


def test_a_plan_is_parsed_resolved_and_ordered(planning):
    assert ("CAL02 Revenue", "Net Revenue") in planning.model.line_items and ("CAL04 Margin", "Margin %") in planning.model.line_items
    r = buildplan.check(planning, PLAN, "Scenario margin")
    assert r["ok"], r
    plan = r["plan"]
    assert [(m["step"], m["name"], m["state"]) for m in plan["modules"]] == [(1, "INP09 Scenario Drivers", "new"), (2, "CAL09 Scenario Margin", "new"), (3, "OUT05 Scenario Pack", "new")]
    # inside a module too: Scenario Revenue is built before Scenario Margin, which reads it
    assert [i["name"] for i in plan["modules"][1]["items"]] == ["Scenario Revenue", "Scenario Margin"]
    c = plan["checks"]
    assert c["formulas"] == c["parsed"] == 4 and c["refs_existing"] == 2 and c["refs_new"] == 5 and c["steps"] == 3
    assert plan["existing"] == ["CAL02 Revenue", "CAL04 Margin"]
    assert ["CAL02 Revenue", "CAL09 Scenario Margin"] in plan["edges"] and ["CAL09 Scenario Margin", "OUT05 Scenario Pack"] in plan["edges"]
    # the order is proven: no step reads a later step, no line item reads a later line item of its own step
    assert buildplan.order_holds(plan)
    step = {m["name"]: m["step"] for m in plan["modules"]}
    for m in plan["modules"]:
        for it in m["items"]:
            for ref in it["refs"]:
                if ref["new"] and ref["module"] != m["name"]:
                    assert step[ref["module"]] < m["step"]
    # and the proof has teeth: swap two steps and it fails
    broken = json.loads(json.dumps(plan)); broken["modules"][1]["step"], broken["modules"][2]["step"] = 3, 2
    assert not buildplan.order_holds(broken)
    # exports
    md = buildplan.to_markdown(plan)
    assert md.index("## What you will build") < md.index("## What already exists that this uses") < md.index("## Line items to build") < md.index("## Steps")
    assert "- **INP09 Scenario Drivers** (new module; dimensions: Scenarios): One flex per scenario." in md and md.index("### CAL09") < md.index("### OUT05") and "| Scenario Revenue | Number |" in md
    assert "1. Create the list Scenarios, unless" in md and "2. Create the module INP09 Scenario Drivers with dimensions Scenarios." in md and "order checked: nothing is built before what it refers to" in md
    rows = list(csv.reader(io.StringIO(buildplan.to_csv(plan))))
    assert rows[0][:3] == ["Step", "Module", "Module state"] and len(rows) == 6 and rows[1][1] == "INP09 Scenario Drivers" and [r[0] for r in rows[1:]] == ["1", "2", "2", "3", "3"]


def test_what_is_rejected(planning):
    def bad(mods):
        r = buildplan.check(planning, mods)
        assert not r["ok"]
        return " | ".join(f"{e['what']}: {e['why']}" for e in r["rejected"])
    one = lambda formula, name="X": [{"name": "CAL09 New", "applies_to": ["Segments"], "line_items": [{"name": name, "formula": formula}]}]
    assert "does not parse" in bad(one("IF 1 THEN"))
    assert "resolves to nothing: no such line item in that module" in bad(one("'CAL02 Revenue'.Missing Item"))
    assert "resolves to nothing: neither a module" in bad(one("'CAL77 Imaginary'.Thing"))
    assert "already exists in the model" in bad([{"name": "CAL02 Revenue", "line_items": [{"name": "Net Revenue", "formula": "1"}]}])
    assert "cycle" in bad([{"name": "CAL09 New", "applies_to": ["Segments"], "line_items": [{"name": "A", "formula": "B + 1"}, {"name": "B", "formula": "A + 1"}]}])
    # two new modules that read each other with no line item waiting on itself are a build Anaplan allows (see
    # test_formats_are_enforced_and_modules_may_read_each_other): accepted, and marked so the steps interleave
    both = buildplan.check(planning, [{"name": "CAL09 P", "line_items": [{"name": "A", "formula": "'CAL10 Q'.B"}, {"name": "C", "formula": "1"}]},
                                      {"name": "CAL10 Q", "line_items": [{"name": "B", "formula": "1"}, {"name": "D", "formula": "'CAL09 P'.C"}]}])
    assert both["ok"] and both["plan"]["interleaved"] and buildplan.order_holds(both["plan"])
    assert "non-empty list" in bad([])
    # adding to an existing module is allowed, and says so
    r = buildplan.check(planning, [{"name": "CAL02 Revenue", "line_items": [{"name": "Net Revenue x2", "formula": "Net Revenue * 2"}]}])
    assert r["ok"] and r["plan"]["modules"][0]["state"] == "exists" and r["plan"]["modules"][0]["items"][0]["refs"][0]["new"] is False


class _B:
    def __init__(self, **kw): self.__dict__.update(kw)


class Planner:
    """Proposes a broken plan, reads the rejection, proposes the fixed one, then writes the Brief."""
    def __init__(self): self.messages = self; self.seen = []

    def create(self, **kw):
        self.seen.append(kw)
        usage = _B(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        results = [json.loads(b["content"]) for m in kw["messages"] if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
        if not results:
            broken = json.loads(json.dumps(PLAN)); broken[1]["line_items"][0]["formula"] = "Scenario Revenue * 'CAL04 Margin'.Margin Percent"
            return _B(content=[_B(type="tool_use", id="t1", name="build_plan", input={"model": "Caldergate Planning", "title": "Scenario margin", "modules": broken})], usage=usage)
        if not results[-1].get("ok"):
            assert "Margin Percent resolves to nothing" in json.dumps(results[-1])
            return _B(content=[_B(type="tool_use", id="t2", name="build_plan", input={"model": "Caldergate Planning", "title": "Scenario margin", "modules": PLAN})], usage=usage)
        return _B(content=[_B(type="text", text="## Brief\n\nThree new modules in three steps: `INP09 Scenario Drivers`, then `CAL09 Scenario Margin`, then `OUT05 Scenario Pack`. "
                                                "It reads `CAL02 Revenue.Net Revenue` and `CAL04 Margin.Margin %` and changes nothing that exists. `CAL88 Ghost` is not part of it.")], usage=usage)


def test_the_plan_reaches_the_page_and_its_new_names_are_not_flagged(tmp_path):
    model = Planner()
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    c = TestClient(app)
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    eid = c.post("/api/estates", data={"name": "Plan", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()["id"]
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "plan", "text": "Give me a plan to build scenario margin."}).json()["turns"][0]
    assert t["kind"] == "plan" and [x["tool"] for x in t["tools"]] == ["build_plan", "build_plan"]
    blk = next(b for b in t["blocks"] if b["type"] == "build_plan")
    assert [m["name"] for m in blk["plan"]["modules"]] == ["INP09 Scenario Drivers", "CAL09 Scenario Margin", "OUT05 Scenario Pack"] and buildplan.order_holds(blk["plan"])
    # the plan's own new modules are known to the validator; an invented one is still flagged
    assert t["unverified"] == ["CAL88 Ghost"] and not t["verification"]["clean"]
    cited = {x["ref"] for x in t["citations"]}
    assert {"CAL02 Revenue.Net Revenue", "CAL04 Margin.Margin %"} <= cited
    md = c.get(f"/api/turns/{t['id']}/plan").text
    assert md.startswith("# Build plan: Scenario margin") and "'INP09 Scenario Drivers'.Revenue Flex %" in md
    assert c.get(f"/api/turns/{t['id']}/plan", params={"format": "csv"}).text.splitlines()[1].startswith("1,INP09 Scenario Drivers,new,Scenarios,1,Revenue Flex %")
    assert c.get("/api/turns/t-nope/plan").status_code == 404


def test_the_plan_as_instructions_with_the_switch_over(planning):
    """The plan reads as instructions: what exists that it uses, numbered steps a builder follows (create the module,
    add each line item, then change the existing formula that switches over, then what to check). A change is checked
    like any formula, and may not close a loop."""
    mods = [{"name": "SYS09 Margin Floor", "applies_to": ["Segments"], "note": "One floor per segment, set by Finance.",
             "line_items": [{"name": "Floor %", "format": "Number", "summary": "None", "formula": ""},
                            {"name": "Floored Margin %", "format": "Number", "summary": "None", "formula": "MAX(Floor %, 'CAL04 Margin'.Margin / 'CAL04 Margin'.Net Revenue)"}]}]
    change = [{"module": "OUT01 Board Pack", "line_item": "net revenue", "formula": "'CAL02 Revenue'.Net Revenue * 'SYS09 Margin Floor'.Floored Margin %", "note": "The pack now shows `OUT01 Board Pack.Net Revenue` after the floor."}]
    r = buildplan.check(planning, mods, "Margin floor", changes=change, checks_after=["Compare `OUT01 Board Pack.Net Revenue` for one segment before and after.", "Set `Floor %` to zero: nothing should move."])
    assert r["ok"], r
    plan = r["plan"]
    assert plan["changes"] == [{"module": "OUT01 Board Pack", "name": "Net Revenue", "old_formula": "'CAL02 Revenue'.Net Revenue", "formula": change[0]["formula"],
                                "refs": plan["changes"][0]["refs"], "note": change[0]["note"]}]
    assert {(x["path"], x["new"]) for x in plan["changes"][0]["refs"]} == {("CAL02 Revenue.Net Revenue", False), ("SYS09 Margin Floor.Floored Margin %", True)}
    assert plan["checks"]["changes"] == 1 and plan["checks"]["formulas"] == plan["checks"]["parsed"] == 2
    # what already exists that the build uses: modules, line items, lists
    assert plan["uses"]["modules"] == ["CAL02 Revenue", "CAL04 Margin", "OUT01 Board Pack"] and plan["uses"]["lists"] == ["Segments"]
    assert {(x["module"], x["name"]) for x in plan["uses"]["line_items"]} == {("OUT01 Board Pack", "Net Revenue"), ("CAL04 Margin", "Margin"), ("CAL04 Margin", "Net Revenue"), ("CAL02 Revenue", "Net Revenue")}
    # the steps, in the order a builder works
    st = plan["steps"]
    assert [x["n"] for x in st] == list(range(1, len(st) + 1)) and [x["kind"] for x in st] == ["module", "line_item", "line_item", "change", "check", "check"]
    assert st[0]["text"] == "Create the module SYS09 Margin Floor with dimensions Segments."
    assert st[1]["text"] == "In SYS09 Margin Floor, add the line item Floor %: format Number, summary None. No formula: it is an input."
    assert st[2]["text"].endswith("Enter its formula:") and st[2]["formula"].startswith("MAX(Floor %")
    assert st[3]["text"].startswith("In OUT01 Board Pack, replace the formula of the existing line item Net Revenue.") and st[3]["old_formula"] == "'CAL02 Revenue'.Net Revenue"
    assert st[4]["text"].startswith("Compare")
    assert not any(w in json.dumps(st).lower() for w in ("candidate", "resolved", "topological"))
    md = buildplan.to_markdown(plan)
    assert "   - from: `'CAL02 Revenue'.Net Revenue`" in md and "5. Check: Compare" in md
    assert list(csv.reader(io.StringIO(buildplan.to_csv(plan))))[-1][1:3] == ["OUT01 Board Pack", "change existing formula"]
    # with a change and no check given, one is written from the change
    assert "before and after the change" in buildplan.check(planning, mods, "x", changes=change)["plan"]["after"][0]
    # an existing module the plan extends is opened, not created
    ext = buildplan.check(planning, [{"name": "CAL04 Margin", "line_items": [{"name": "Margin after floor", "formula": "Margin"}]}])["plan"]["steps"]
    assert ext[0]["kind"] == "open" and ext[0]["text"].startswith("Open the existing module CAL04 Margin")

    def bad(**kw):
        r = buildplan.check(planning, kw.pop("mods", mods), "x", **kw)
        assert not r["ok"]
        return " | ".join(f"{e['what']}: {e['why']}" for e in r["rejected"])
    assert "a change names a line item the model does not have" in bad(changes=[{"module": "OUT01 Board Pack", "line_item": "Nope", "formula": "1"}])
    assert "does not parse" in bad(changes=[{"module": "OUT01 Board Pack", "line_item": "Net Revenue", "formula": "IF THEN ("}])
    assert "resolves to nothing" in bad(changes=[{"module": "OUT01 Board Pack", "line_item": "Net Revenue", "formula": "'SYS09 Margin Floor'.Missing"}])
    assert "already has: nothing changes" in bad(changes=[{"module": "OUT01 Board Pack", "line_item": "Net Revenue", "formula": "'CAL02 Revenue'.Net Revenue"}])
    assert "list it under changes" in bad(mods=[{"name": "CAL04 Margin", "line_items": [{"name": "Margin", "formula": "1"}]}])
    # the changed line item may not read a new line item that reads it
    assert "a circular reference" in bad(changes=[{"module": "CAL04 Margin", "line_item": "Margin", "formula": "'SYS09 Margin Floor'.Floored Margin % * Net Revenue"}])
    # the changed line item is listed with what exists; a list the plan needs is created first, described in the plan's words
    assert plan["uses"]["line_items"][0] == {"module": "OUT01 Board Pack", "name": "Net Revenue"}
    sub = buildplan.check(planning, [{"name": "CAL10 Driver Values", "applies_to": ["Segments", "Margin Drivers"], "line_items": [{"name": "Value", "formula": ""}]}],
                          lists=[{"name": "Margin Drivers", "what": "a line item subset of `CAL04 Margin` holding Margin and Net Revenue"}])["plan"]
    assert sub["new_lists"] == ["Margin Drivers"] and sub["steps"][0]["text"] == "Create Margin Drivers: a line item subset of `CAL04 Margin` holding Margin and Net Revenue."
    assert sub["steps"][1]["text"] == "Create the module CAL10 Driver Values with dimensions Segments, Margin Drivers."
    assert "names `CAL77 Nope`" in bad(lists=[{"name": "Margin Drivers", "what": "a subset of `CAL77 Nope`"}])
    # a name in backticks in a check or a note must exist
    assert "names `CAL99 Ghost`" in bad(checks_after=["Open `CAL99 Ghost` and look."])


def test_a_change_that_closes_a_loop_through_existing_line_items_is_refused(planning):
    """Review 2026-11-13, item 2: only a new line item that read the changed one directly was caught. The model's own
    formulas are walked too: CAL04 Margin.Net Revenue reads CAL02 Revenue.Segment, so Segment may not come to read
    Net Revenue, directly or through anything the plan builds or the model already has."""
    assert ("CAL02 Revenue", "Segment") in planning.graph.edges[("CAL04 Margin", "Net Revenue")]
    mods = [{"name": "SYS09 Helper", "applies_to": ["Segments"], "line_items": [{"name": "Via", "format": "Number", "formula": "'CAL04 Margin'.Net Revenue"}]}]
    def why(mods, changes):
        r = buildplan.check(planning, mods, "x", changes=changes)
        return "" if r["ok"] else " | ".join(f"{e['what']}: {e['why']}" for e in r["rejected"])
    # directly: the changed formula reads an existing line item that reads the changed one
    assert "a circular reference" in why([], [{"module": "CAL02 Revenue", "line_item": "Segment", "formula": "'CAL04 Margin'.Net Revenue"}])
    # through a new line item that reads an existing one that reads the changed one
    assert "a circular reference" in why(mods, [{"module": "CAL02 Revenue", "line_item": "Segment", "formula": "'SYS09 Helper'.Via"}])
    # through two existing steps: CAL04 Margin.Margin reads Net Revenue, which reads Segment
    assert "a circular reference" in why([], [{"module": "CAL02 Revenue", "line_item": "Segment", "formula": "'CAL04 Margin'.Margin"}])
    # two changes that only loop together
    assert "a circular reference" in why([], [{"module": "OUT01 Board Pack", "line_item": "Revenue", "formula": "Revenue Copy 2 + 1"}])
    # and a change that reads nothing downstream of itself is still accepted; the old formula's own edge is not counted against the new one
    assert why([], [{"module": "CAL04 Margin", "line_item": "Net Revenue", "formula": "'CAL02 Revenue'.Gross Revenue"}]) == ""
    assert why([], [{"module": "OUT01 Board Pack", "line_item": "Revenue Copy", "formula": "'CAL02 Revenue'.Net Revenue"}]) == ""


def test_formats_are_enforced_and_modules_may_read_each_other(planning):
    """Review 2026-11-13, item 10. A format Anaplan does not have was accepted. Two new modules that read each other
    were refused although no line item waits on itself, which Anaplan allows: the plan is accepted and its steps build
    the line items in an order that works, across both modules."""
    r = buildplan.check(planning, [{"name": "SYS09 X", "applies_to": ["Segments"], "line_items": [{"name": "A", "format": "Banana", "formula": ""}]}])
    assert not r["ok"] and "Banana" in r["rejected"][0]["why"] and "Number" in r["rejected"][0]["why"]
    ok = buildplan.check(planning, [{"name": "SYS09 X", "applies_to": ["Segments"], "line_items": [
        {"name": "A", "format": "list: Segments", "formula": ""}, {"name": "B", "format": "number", "formula": ""}, {"name": "C", "format": "Time Period", "formula": ""}, {"name": "D", "formula": ""}]}])
    assert ok["ok"] and [i["format"] for i in ok["plan"]["modules"][0]["items"]] == ["List: Segments", "Number", "Time period", "Number"]
    mods = [{"name": "CAL20 Left", "applies_to": ["Segments"], "line_items": [{"name": "Base", "formula": "'CAL02 Revenue'.Net Revenue"}, {"name": "Final", "formula": "'CAL21 Right'.Adjusted * 2"}]},
            {"name": "CAL21 Right", "applies_to": ["Segments"], "line_items": [{"name": "Adjusted", "formula": "'CAL20 Left'.Base + 1"}]}]
    r = buildplan.check(planning, mods, "Two modules that read each other")
    assert r["ok"], r
    plan = r["plan"]
    assert plan["interleaved"] is True and buildplan.order_holds(plan)
    st = [(s["kind"], s.get("module"), s.get("item")) for s in plan["steps"]]
    assert st == [("module", "CAL20 Left", None), ("module", "CAL21 Right", None), ("line_item", "CAL20 Left", "Base"), ("line_item", "CAL21 Right", "Adjusted"), ("line_item", "CAL20 Left", "Final")]
    # a line item that waits on itself through the other module is still refused
    loop = [{"name": "CAL20 Left", "line_items": [{"name": "Base", "formula": "'CAL21 Right'.Adjusted"}]}, {"name": "CAL21 Right", "line_items": [{"name": "Adjusted", "formula": "'CAL20 Left'.Base"}]}]
    assert "cycle" in buildplan.check(planning, loop)["rejected"][0]["why"]
    # a plan whose modules do not read each other is not interleaved, and its steps go module by module as before
    assert buildplan.check(planning, PLAN)["plan"]["interleaved"] is False
