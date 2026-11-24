"""Suggested next questions (Karim, 2026-11-16): answers are short on purpose, so the depth is in the second and third
question. Under every answer are two or three questions to ask next, one click each, that lead from one feature into
another. They are made by code from what the answer was about: no model call, and never a name the model lacks."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect import followups
from test_access import _B, _workspace, _no_real_backend      # noqa: F401
from test_calc import Explains

LI = {"kind": "line_item", "ref": "CAL10 Depreciation.Charge", "model": "Caldergate FP&A"}
MOD = {"kind": "module", "ref": "CAL03 Opex", "model": "Caldergate FP&A"}


def test_each_kind_of_answer_leads_into_other_features():
    f = lambda kind, subject, **kw: [x["text"] for x in followups.suggest(kind, subject, **kw)]
    calc = f("calculation", LI)
    assert calc == ["Why is CAL10 Depreciation.Charge built this way?", "What are the implications of changing CAL10 Depreciation.Charge?",
                    "What do the project documents say about CAL10 Depreciation.Charge?"]
    assert f("why", LI)[0] == "How is CAL10 Depreciation.Charge calculated?" and "Give me a plan" in " ".join(f("why", LI))
    assert all("calculated" not in q for q in f("why", MOD))                 # a module has no formula to take apart
    assert f("implications", MOD) == ["What should I test before changing CAL03 Opex?", "What do the project documents say about CAL03 Opex?",
                                      "Why is CAL03 Opex built this way?"]
    assert f("documents", MOD)[0] == "Why is CAL03 Opex built this way?"
    plan = f("plan", LI, flags=3)
    assert plan[0] == "What are the implications of changing CAL10 Depreciation.Charge?" and "Explain the Planual flags on this plan." in plan
    assert "Explain the Planual flags on this plan." not in f("plan", LI, flags=0)
    assert f("improve", LI)[0] == "Give me a plan for the first fix."
    assert f("why", MOD, not_recorded=True)[0] == "What do the project documents say about CAL03 Opex?"
    assert f("overview", None) and f("count", None)
    # never more than three, never the kind of question that was just answered, each says which feature it leads to
    for kind in followups.KINDS:
        for subj in (LI, MOD, None):
            out = followups.suggest(kind, subj)
            assert len(out) <= 3 and all(x["leads_to"] != kind or kind in ("general", "why") for x in out) and all(x["text"].endswith(("?", ".")) for x in out)
    # no subject, nothing made up
    assert all("None" not in x["text"] for kind in followups.KINDS for x in followups.suggest(kind, None))


def test_the_answer_carries_them_and_they_name_only_what_the_answer_was_about(tmp_path):
    c = TestClient(create_app(tmp_path / "data", client_factory=lambda: Explains()))
    eid = _workspace(c, "Margins")
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "How is margin % calculated?"}).json()["turns"][0]
    b = t["blocks"][-1]
    assert b["type"] == "followups" and 2 <= len(b["items"]) <= 3
    assert b["items"][0] == {"text": "Why is CAL04 Margin.Margin % built this way?", "leads_to": "why"}
    assert all("CAL04 Margin.Margin %" in x["text"] for x in b["items"])
    # stored with the turn, so the page draws them again without asking the model
    cid = c.get(f"/api/estates/{eid}/conversations").json()[0]["id"]
    assert c.get(f"/api/conversations/{cid}").json()["turns"][0]["blocks"][-1]["type"] == "followups"
    # no model call was spent on them
    assert t["run"]["model_calls"] == 2


def test_an_answer_that_names_a_real_object_without_looking_it_up_still_gets_its_next_questions():
    """Found making the guide: a why-answer that rested on documents named `CAL03 Opex.Forecast Opex` without any tool
    handing it, so it had no cited object and was given no next questions at all. A name the answer uses that the
    workspace really has is a subject too; and with no object at all an answer still offers where to go next."""
    cited = [{"kind": "document", "ref": "s-0123456789"}, {"kind": "model", "ref": "Caldergate FP&A"}]
    real = [{"kind": "line_item", "ref": "CAL03 Opex.Forecast Opex", "model": "Caldergate FP&A"}, {"kind": "module", "ref": "CAL03 Opex", "model": "Caldergate FP&A"}]
    text = "## Brief\n\nThe mapping in `CAL03 Opex.Forecast Opex` was deliberate."
    assert followups.subject_of([], cited, text) is None
    s = followups.subject_of([], cited, text, named=real)
    assert s == {"kind": "line_item", "ref": "CAL03 Opex.Forecast Opex", "model": "Caldergate FP&A"}
    assert [x["text"] for x in followups.suggest("why", s)][0] == "How is CAL03 Opex.Forecast Opex calculated?"
    for kind in followups.KINDS:
        assert followups.suggest(kind, None), kind                         # never nothing
    assert followups.suggest("why", None, not_recorded=True)
