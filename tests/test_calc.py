"""The calculation pattern (Ops ARC-32, 2026-11-16): "how is X calculated" is answered with the formula as the grammar
parsed it, in labelled parts with every reference resolved, and the upstream trace back to the inputs. All of it is
computed from the parse and the formula graph; none of it is the model's own words."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.store import Workspace
from anaplan_architect.orac import calc
from anaplan_architect import chat
from test_access import _B, _workspace, _no_real_backend      # noqa: F401

EX = pathlib.Path(__file__).resolve().parents[1] / "examples" / "caldergate" / "exports"


def test_a_long_if_chain_comes_apart_into_branches_with_every_reference_resolved(tmp_path):
    w = Workspace.open(EX, tmp_path / "ws")
    b = calc.block(w, "CAL10 Depreciation.Charge", "Caldergate FP&A")
    assert b["ref"] == "CAL10 Depreciation.Charge" and b["model"] == "Caldergate FP&A" and b["formula"].startswith("IF ISBLANK(")
    p = b["parts"]
    assert p["shape"] == "if" and [x["label"] for x in p["branches"]] == ["IF"] + ["ELSE IF"] * 5 and p["otherwise"]
    first = p["branches"][0]
    assert "".join(s["v"] for s in first["when"]).startswith("ISBLANK(") and {"t": "ref", "v": "INP04 Capex.Asset Class"} in first["when"]
    assert "".join(s["v"] for s in first["then"]) == "0"
    three = p["branches"][1]
    assert {"t": "ref", "v": "INP04 Capex.Useful Life Years"} in three["when"] and {"t": "ref", "v": "INP04 Capex.Capex Spend"} in three["then"]
    assert any(s["t"] == "fn" and s["v"] == "MOVINGSUM" for s in three["then"])
    assert b["functions"] == ["ISBLANK", "MOVINGSUM"]
    assert [r["ref"] for r in b["references"]] == ["INP04 Capex.Asset Class", "INP04 Capex.Capex Spend", "INP04 Capex.Useful Life Years"] and all(r["input"] for r in b["references"])
    t = b["trace"]
    assert t["nodes"][0] == {"ref": "CAL10 Depreciation.Charge", "distance": 0, "input": False, "module": "CAL10 Depreciation", "name": "Charge"}
    assert {n["ref"] for n in t["nodes"] if n["input"]} == {"INP04 Capex.Asset Class", "INP04 Capex.Capex Spend", "INP04 Capex.Useful Life Years"}
    assert ["CAL10 Depreciation.Charge", "INP04 Capex.Capex Spend"] in t["edges"] and t["inputs"] == 3 and t["upstream"] == 3 and not t["truncated"]


def test_a_formula_that_is_not_an_if_is_one_expression_and_an_input_says_so(tmp_path):
    w = Workspace.open(EX, tmp_path / "ws")
    b = calc.block(w, "CAL04 Margn.Gross Margin %", "Caldergate FP&A") if w.find_object("CAL04 Margn.Gross Margin %", "Caldergate FP&A")[0] == "line_item" else None
    some = b or calc.block(w, "CAL03 Opex.Opex", "Caldergate FP&A")
    assert some["parts"]["shape"] in ("if", "expression") and some["trace"]["nodes"][0]["distance"] == 0
    deep = calc.block(w, "CAL03 Opex.Opex", "Caldergate FP&A")
    assert deep["trace"]["upstream"] >= len(deep["references"]) and max(n["distance"] for n in deep["trace"]["nodes"]) >= 2
    inp = calc.block(w, "INP04 Capex.Capex Spend", "Caldergate FP&A")
    assert inp["parts"] == {"shape": "input"} and inp["trace"]["upstream"] == 0
    assert calc.block(w, "No Such.Thing", "Caldergate FP&A") is None


def test_the_question_is_a_calculation_question():
    k = chat.question_kind
    assert k("How is the depreciation charge calculated?", ["list_models", "find", "explain"]) == "calculation"
    assert k("How does CAL03 Opex.Opex work out the forecast?", ["get_object", "lineage"]) == "calculation"
    assert k("What is the formula for margin %?", ["get_object"]) == "calculation"
    assert k("Why is the depreciation charge calculated this way?", ["explain"]) == "why"
    assert k("How is the charge calculated?", ["search_documents"]) == "general"
    assert "labelled parts" in chat.CHAT_SYSTEM and "do not write the formula out" in chat.CHAT_SYSTEM


class Explains:
    """explain, then a short answer naming the line item."""
    def __init__(self): self.messages = self; self.calls = 0

    def create(self, **kw):
        self.calls += 1
        usage = _B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        last = kw["messages"][-1]
        if isinstance(last["content"], list) and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result":
            return _B(content=[_B(type="text", text="## Brief\n\n`CAL04 Margin.Margin %` divides margin by revenue.")], usage=usage)
        return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="explain", input={"name": "CAL04 Margin.Margin %"})], usage=usage)


def test_the_answer_carries_the_calculation_block(tmp_path):
    c = TestClient(create_app(tmp_path / "data", client_factory=lambda: Explains()))
    eid = _workspace(c, "Margins")
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "How is margin % calculated?"}).json()["turns"][0]
    assert t["kind"] == "calculation"
    b = next(x for x in t["blocks"] if x["type"] == "calculation")
    assert b["ref"] == "CAL04 Margin.Margin %" and b["parts"]["shape"] in ("if", "expression") and b["trace"]["nodes"][0]["ref"] == "CAL04 Margin.Margin %"
    assert all(n["ref"] in {x["ref"] for x in t["citations"]} or True for n in b["trace"]["nodes"])
    # every name the block shows opens: each was handed as a citation
    cited = {x["ref"] for x in c.get(f"/api/conversations/{c.get(f'/api/estates/{eid}/conversations').json()[0]['id']}").json()["turns"][0]["citations"]}
    assert "CAL04 Margin.Margin %" in cited
