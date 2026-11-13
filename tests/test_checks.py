"""The tests of anaplan-estate's catalogue as the architect shows them: the rows and the rollup, the chat tool, the
route Home reads, and the test numbers on a rule's evidence and on a plan card."""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_estate import checks as echecks
from anaplan_architect.orac import checks as checksmod
from anaplan_architect.store import Workspace
from anaplan_architect import tools, chat
from anaplan_architect.web import create_app
from test_web import _Fake, _upload, FX

COUNTS = ("total", "found", "clear", "not_run")


def test_rows_rollup_and_names(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws"); w.snapshot_id = "s1"
    rows = checksmod.of(w)
    assert rows is checksmod.of(w)                                   # worked out once per parse
    assert [r["num"] for r in rows] == [c.num for c in echecks.CHECKS] and all(r["status"] in checksmod.STATUSES for r in rows)
    roll = checksmod.rollup(rows)
    assert roll["total"] == len(echecks.CHECKS) == roll["found"] + roll["clear"] + roll["not_run"]
    assert [a["num"] for a in roll["areas"]] == [c.num for c in echecks.CATEGORIES] and sum(a["total"] for a in roll["areas"]) == roll["total"]
    assert all(a["total"] == a["found"] + a["clear"] + a["not_run"] for a in roll["areas"])
    assert all(r["not_run"] and all(n["why"] for n in r["not_run"]) for r in rows if r["status"] == "not run")    # a test not run says why
    found = [r for r in rows if r["status"] == "found"]
    assert found and all(r["hits"] > 0 for r in found)
    fids = {f.id for f in w.estate.findings}
    assert all(f["id"] in fids and f["title"] for r in rows for f in r["findings"])
    rule = next(r for r in rows if r["rules"])["rules"][0]
    named = checksmod.for_rule(rule)
    assert named and {t["num"] for t in named} <= {r["num"] for r in rows if rule in r["rules"]} and all(t["title"] for t in named)
    assert checksmod.for_rule("NO-SUCH-RULE") == []
    assert checksmod.named(["1.1", "99.9"]) == [{"num": "1.1", "title": echecks.BY_NUM["1.1"].title}]
    h = checksmod.handles()
    first, area = echecks.CHECKS[0], echecks.CATEGORIES[0]
    assert {first.key, "test:1.1", first.title.lower(), f"1.1 {first.title}".lower(), area.title.lower(), f"1 {area.title}".lower(), "calculation effort", "referenced by"} <= h
    real = {x.lower() for m in w.estate.models for x in m.model.modules}
    assert (h - real) <= chat._handles(w) and not (real & chat._handles(w) & h)      # a handle, never a name not found; and never in place of a real object
    text = f"Test `1.1 {first.title}` in area `1 {area.title}` needs the `Calculation Effort` column; `Ghost.Nope` is not there."
    assert chat.assess_answer(text, w)["unverified"] == ["Ghost.Nope"]


def test_the_tool_answers_what_was_checked(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws"); w.snapshot_id = "s1"
    tb = tools.Toolbox(w)
    assert any(t["name"] == "tests" for t in tools.Toolbox.schema())
    every = json.loads(tb.call("tests", {}))
    assert len(every["tests"]) == every["total"] == len(echecks.CHECKS) and every["found"] + every["clear"] + every["not_run"] == every["total"]
    assert len(every["areas"]) == len(echecks.CATEGORIES) and "what" not in every["tests"][0]          # the long list stays short per row
    found = json.loads(tb.call("tests", {"status": "found"}))
    assert found["tests"] and all(t["status"] == "found" for t in found["tests"]) and len(found["tests"]) == every["found"]
    assert len(json.loads(tb.call("tests", {"status": "not_run"}))["tests"]) == every["not_run"]
    one = json.loads(tb.call("tests", {"number": found["tests"][0]["test"]}))
    assert len(one["tests"]) == 1 and one["tests"][0]["what"] and "needs" in one["tests"][0]
    withrule = next((t for t in found["tests"] if t.get("rules")), None)
    assert withrule is None or withrule["rules"][0] in found["cites"]                                   # a rule behind a test is handed as a citation
    assert "error" in json.loads(tb.call("tests", {"number": "99.9"})) and "error" in json.loads(tb.call("tests", {"status": "maybe"}))
    assert len(json.loads(tb.call("tests", {"area": 1}))["tests"]) == sum(1 for c in echecks.CHECKS if c.category == 1)


def test_home_summary_the_route_the_drawer_and_the_cards(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    s = c.get(f"/api/estates/{eid}").json()
    t = s["tests"]
    assert t["total"] == len(echecks.CHECKS) and len(t["areas"]) == len(echecks.CATEGORIES) and t["found"] >= 1
    d = c.get(f"/api/estates/{eid}/tests").json()
    assert d["snapshot"] == s["snapshot"]["id"] and len(d["tests"]) == t["total"] and {k: d[k] for k in COUNTS} == {k: t[k] for k in COUNTS}
    row = next(r for r in d["tests"] if r["status"] == "found" and r["rules"])
    rule = row["rules"][0]
    ev = c.get(f"/api/estates/{eid}/object", params={"ref": rule["ref"], "kind": "finding"}).json()
    assert ev["id"] == rule["id"]                                                                       # the rule opens by the id the row carries
    named = ev["object"]["tests"]                                                                       # the drawer shows the tests the rule belongs to
    assert named and {x["num"] for x in named} <= {r["num"] for r in d["tests"] if any(y["ref"] == rule["ref"] for y in r["rules"])}
    plan = c.get(f"/api/estates/{eid}/plan").json()
    assert plan["actions"] and all([x["num"] for x in a["tests_named"]] == a["tests"] and all(x["title"] for x in a["tests_named"]) for a in plan["actions"])
