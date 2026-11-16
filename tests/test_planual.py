"""Planual flags and the 'you supply' slot (Ops ARC-32, 2026-11-16).

Flags are advisory: a planned line item is marked as per a Planual rule number or as departing from it, with one line
of why; a departure never rejects a plan. Only rule numbers and the tool's own wording are shown. A plan that needs
something an export cannot hold (a list member's name) is still built, with that value as a marked slot the builder
fills, listed once."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from anaplan_estate import lint as elint
from anaplan_architect.store import Workspace
from anaplan_architect.orac import planual, buildplan
from anaplan_architect.tools import Toolbox
from anaplan_architect.orac.evidence import Evidence
from anaplan_architect import chat

EX = pathlib.Path(__file__).resolve().parents[1] / "examples" / "caldergate" / "exports"
FPA = "Caldergate FP&A"


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return Workspace.open(EX, tmp_path_factory.mktemp("ws") / "ws")


def _plan(w, modules, changes=None):
    r = buildplan.check(w.models()[FPA], modules, "Legal fees", changes=changes or [])
    assert r["ok"], r.get("rejected")
    return r["plan"]


MODS = [{"name": "CAL20 Legal", "applies_to": ["Cost Centres"], "line_items": [
    {"name": "Uplifted Fees", "format": "Number", "summary": "Sum", "formula": "'INP02 Opex Drivers'.Legal Fees * 1.37"},
    {"name": "Fees Clean", "format": "Number", "summary": "None", "formula": "IF 'INP02 Opex Drivers'.Legal Fees > 0 THEN 'INP02 Opex Drivers'.Legal Fees ELSE 0"},
    {"name": "Label", "format": "Text", "summary": "None", "formula": ""}]}]


def test_what_can_be_flagged_is_counted_and_said_modestly():
    c = planual.catalogue()
    assert c["numbers"] == 18 and c["checks"] == 24
    assert "18 rule numbers across 24 checks" in c["line"] and "does not check the Planual" in c["line"]
    assert planual.label("A-IF-COUNT", "as_per") == "As per Planual 2.02-01, 2.02-02" and planual.label("A-TEXT-FORMAT") == "Departs from Planual 2.03-02"
    assert planual.label("F-DIVIDE-FN") == "Departs from the tool's own test"


def test_planned_line_items_are_flagged_as_per_or_departing_and_nothing_is_rejected(w):
    plan = planual.attach(w.models()[FPA], _plan(w, MODS))
    fl = plan["planual"]["flags"]
    get = lambda obj, rule: next((f for f in fl if f["object"] == obj and f["rule"] == rule), None)
    hard = get("CAL20 Legal.Uplifted Fees", "F-HARDCODE")
    assert hard and hard["state"] == "departs" and hard["label"] == "Departs from Planual 2.01-09, 2.02-12" and "1.37" in hard["why"]
    assert get("CAL20 Legal.Label", "A-TEXT-FORMAT")["label"] == "Departs from Planual 2.03-02"
    assert get("CAL20 Legal.Uplifted Fees", "A-SUMMARY-ON")["state"] == "departs"
    ifs = get("CAL20 Legal.Fees Clean", "A-IF-COUNT")
    assert ifs["state"] == "as_per" and ifs["label"] == "As per Planual 2.02-01, 2.02-02" and ifs["why"].startswith("1 IF")
    assert get("CAL20 Legal.Fees Clean", "A-SUMMARY-ON")["state"] == "as_per"
    # each flag is on its line item too, and departures come first
    items = {it["name"]: it for it in plan["modules"][0]["items"]}
    assert [f["state"] for f in items["Uplifted Fees"]["flags"]][0] == "departs" and items["Fees Clean"]["flags"] and all(f["state"] == "as_per" for f in items["Fees Clean"]["flags"])
    assert plan["planual"]["departs"] >= 3 and plan["planual"]["as_per"] >= 2 and "does not reject" in plan["planual"]["note"]
    # only numbers and the tool's own words: no sentence of the Planual's is in any flag
    said = " ".join(f["label"] + " " + f["why"] for f in fl).lower()
    assert not any(title.lower() in said for title in elint.PLANUAL.values())
    # the model itself was not touched
    assert ("CAL20 Legal", "Label") not in w.models()[FPA].model.line_items


def test_a_changed_formula_is_flagged_on_its_new_text(w):
    old = w.models()[FPA].model.line_items[("CAL03 Opex", "Forecast Opex")].formula
    new = "IF ITEM(Accounts) = Accounts.'6500 Legal' THEN 'INP02 Opex Drivers'.Legal Fees ELSE " + old
    plan = planual.attach(w.models()[FPA], _plan(w, [], [{"module": "CAL03 Opex", "line_item": "Forecast Opex", "formula": new}]))
    f = next(x for x in plan["changes"][0]["flags"] if x["rule"] == "A-IF-COUNT")
    assert f["state"] == "departs" and "Planual 2.02-01" in f["label"] and "13" in f["why"]


def test_the_tool_returns_the_flags_with_the_plan(w):
    tb = Toolbox(w, Evidence("e", "s"))
    r = tb.build_plan(FPA, "Legal fees", MODS)
    assert r.get("ok") is not False and r["plan"]["planual"]["departs"] >= 3
    # the flags go to the model in a short form so it can say them, and it is told they are advisory
    assert any("Departs from Planual 2.03-02" in str(x) for x in r["planual"]) and "advisory" in r["planual_note"]
    assert "Planual" in chat.CHAT_SYSTEM and "never the Planual's text" in chat.CHAT_SYSTEM


def test_a_plan_is_built_with_a_slot_the_builder_fills(w):
    old = w.models()[FPA].model.line_items[("CAL03 Opex", "Forecast Opex")].formula
    slot = "Accounts.'YOU SUPPLY: the legal fees account, with its code'"
    new = old.replace("ELSE IF ITEM(Accounts) = Accounts.'6110 Rates'", f"ELSE IF ITEM(Accounts) = {slot} THEN 'INP02 Opex Drivers'.Legal Fees ELSE IF ITEM(Accounts) = Accounts.'6110 Rates'")
    assert new != old
    r = buildplan.check(w.models()[FPA], [], "Legal fees driver", changes=[{"module": "CAL03 Opex", "line_item": "Forecast Opex", "formula": new}])
    assert r["ok"], r.get("rejected")
    sup = r["plan"]["supply"]
    assert sup == [{"slot": slot, "list": "Accounts", "what": "the legal fees account, with its code", "where": ["CAL03 Opex.Forecast Opex"]}]
    assert any(s["kind"] == "supply" and "legal fees account" in s["text"] for s in r["plan"]["steps"])
    md = buildplan.to_markdown(r["plan"])
    assert "You supply" in md and "the legal fees account, with its code" in md
    # a slot is only for what an export cannot hold: a member of a list the model has. Anywhere else it is an unresolved reference.
    bad = buildplan.check(w.models()[FPA], [{"name": "CAL21 X", "line_items": [{"name": "A", "format": "Number", "formula": "'YOU SUPPLY: some module'.Thing"}]}], "x")
    assert not bad["ok"]
    # the validator does not flag the slot as a name the estate lacks
    tb = Toolbox(w, Evidence("e", "s"))
    out = tb.build_plan(FPA, "Legal fees driver", [], changes=[{"module": "CAL03 Opex", "line_item": "Forecast Opex", "formula": new}])
    assert out["plan"]["supply"] and "you_supply" in out
    a = chat.assess_answer(f"## Brief\n\nFill `{slot}` in `CAL03 Opex.Forecast Opex`.", w, tb.ev, tb.planned)
    assert a["unverified"] == [] and slot not in a["unchecked"]
    assert "YOU SUPPLY" in chat.CHAT_SYSTEM


def test_improve_cards_carry_the_rule_number_and_what_was_decided(tmp_path):
    """Each finding card says which Planual rule numbers its finding rests on, or that it is the tool's own test; and where
    the owner has recorded a deliberate exception (a decision or constraint note on the object, a document section that
    names it and says it is kept or deferred, or the card's own state) the card says kept on purpose and points at it."""
    from fastapi.testclient import TestClient
    from anaplan_architect.web import create_app
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    assert c.post("/api/demo/reset").status_code == 200
    plan = c.get("/api/estates/caldergate-demo/plan").json()
    cards = plan["actions"]
    assert all("rule_label" in x and isinstance(x["planual"], list) for x in cards)
    assert any(x["planual"] and x["rule_label"].startswith("Planual 2.") for x in cards) and any(not x["planual"] and x["rule_label"] == "the tool's own test" for x in cards)
    old = next(x for x in cards if any(o.startswith("CAL05 Opex OLD") for o in x["objects"]))
    k = old["kept"]
    assert k and k["by"] == "note" and "kept on purpose" in k["title"] and k["id"].startswith("n-") and k["citation"]
    assert sum(1 for x in cards if x["kept"]) < len(cards)                     # not everything is an exception
    # the architect is told the same through its tool, with ids it can cite
    w = app.state.workspaces[next(k for k in app.state.workspaces if k[0] == "caldergate-demo")]
    from anaplan_architect.chat import Session
    rows = Toolbox(w, Evidence("caldergate-demo", w.snapshot_id)).action_plan(include_below_bar=True)["actions"]
    r = next(x for x in rows if any("CAL05 Opex OLD" in str(o) for o in x["objects"]))
    assert r["rule"] and "kept_on_purpose" in r and "n-" in r["kept_on_purpose"]
