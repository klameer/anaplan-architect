"""Documents tied to objects, made visible (Ops ARC-32, 2026-11-16).

When a document is read in, each section is linked to the modules and line items it names. That link is now shown both
ways: on the object ("named in 3 sections of 2 documents"), and on the section (the objects it names); and a question
about what the documents say of an object is answered from the link first, keyword search second."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import pytest
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import documents as docsmod
from anaplan_architect.tools import Toolbox
from anaplan_architect.orac.evidence import Evidence
from anaplan_architect import chat
from test_access import _B, _no_real_backend      # noqa: F401

EID = "caldergate-demo"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    app = create_app(tmp_path_factory.mktemp("data") / "data", client_factory=lambda: None)
    c = TestClient(app)
    assert c.post("/api/demo/reset").status_code == 200
    return app, c


def test_a_quote_keeps_the_object_names_inside_it():
    """The showcase run's question 8 was flagged because the architect wrote the object names inside a quoted passage in
    backticks, and the check blanked them out before looking for the passage. A name in backticks inside a quotation is
    part of the quotation."""
    sec = {"s-0123456789": {"text": "It was replaced by CAL03 Opex in 2021, when the driver-based forecast moved to a single formula."}}
    ans = 'The record says: "It was replaced by `CAL03 Opex` in 2021, when the driver-based forecast moved to a single formula." `s-0123456789`'
    q = docsmod.check_quotes(ans, sec)
    assert len(q) == 1 and q[0]["found"] and "CAL03 Opex" in q[0]["quote"]
    # and a passage that is not there is still caught, names or no names
    bad = docsmod.check_quotes('"It was replaced by `CAL03 Opex` in 2019, by the first partner." `s-0123456789`', sec)
    assert len(bad) == 1 and not bad[0]["found"] and bad[0]["checked"]
    # a name in backticks outside any quotation is still not a quotation
    assert docsmod.check_quotes("See `CAL03 Opex` in `s-0123456789`.", sec) == []


def test_the_link_from_an_object_to_the_sections_that_name_it(demo):
    app, c = demo
    a = docsmod.about(app.state.db, EID, "CAL03 Opex")
    assert len(a["sections"]) >= 3 and a["documents"] >= 2 and a["named_in"] == f"named in {len(a['sections'])} sections of {a['documents']} documents"
    s = a["sections"][0]
    assert s["section"].startswith("s-") and s["document"] and s["snippet"] and any(n.startswith("CAL03 Opex") for n in s["names"])
    li = docsmod.about(app.state.db, EID, "CAL03 Opex.Forecast Opex")
    assert 1 <= len(li["sections"]) <= len(a["sections"]) and all("CAL03 Opex.Forecast Opex" in x["names"] for x in li["sections"])
    assert docsmod.about(app.state.db, EID, "No Such Module")["named_in"] == "named in no document"


def test_the_object_and_the_documents_page_show_the_link_both_ways(demo):
    app, c = demo
    o = c.get(f"/api/estates/{EID}/object", params={"ref": "CAL03 Opex", "kind": "module", "model": "Caldergate FP&A"}).json()
    d = o["object"]["documents"]
    assert d["named_in"].startswith("named in ") and len(d["sections"]) >= 3 and d["sections"][0]["heading"] is not None
    docs = c.get(f"/api/estates/{EID}/documents").json()["documents"]
    named = [s for doc in docs for s in doc["sections"] if s.get("names")]
    assert named and any("CAL03 Opex" in n for s in named for n in s["names"])


def test_the_architect_reads_the_link_first(demo):
    app, c = demo
    w = app.state.workspaces[next(k for k in app.state.workspaces if k[0] == EID)]
    tb = Toolbox(w, Evidence(EID, w.snapshot_id))
    r = tb.object_documents("CAL03 Opex")
    assert r["object"] == "CAL03 Opex" and r["named_in"].startswith("named in ") and len(r["sections"]) >= 3
    assert all(s["section"] in tb.sections for s in r["sections"]) and "get_section" in r["note"]
    assert "object_documents" in [t["name"] for t in Toolbox.schema()]
    k = chat.question_kind
    assert k("What do the project documents say about CAL03 Opex?", ["list_models", "object_documents", "get_section"]) == "documents"
    assert k("Why do the documents say CAL03 Opex was built?", ["object_documents"]) == "why"
    s = chat.CHAT_SYSTEM
    assert "object_documents first" in s and "inside the quoted text" in s and "disagree" in s


class Reads:
    """object_documents, get_section on the first section, then an answer quoting it with the name in backticks."""
    def __init__(self): self.messages = self; self.calls = 0; self.sid = None

    def create(self, **kw):
        import re, json
        self.calls += 1
        usage = _B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        last = kw["messages"][-1]
        tool = isinstance(last["content"], list) and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result"
        if not tool:
            return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="object_documents", input={"name": "CAL03 Opex"})], usage=usage)
        text = " ".join(str(r.get("content")) for r in last["content"])
        if self.sid is None:
            self.sid = re.search(r"s-[0-9a-f]{10}", text).group(0)
            return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="get_section", input={"section": self.sid})], usage=usage)
        return _B(content=[_B(type="text", text=f"## Brief\n\nThe documents name `CAL03 Opex` in several places (`{self.sid}`).")], usage=usage)


def test_the_answer_carries_the_link_as_a_block(tmp_path):
    app = create_app(tmp_path / "data", client_factory=lambda: Reads())
    c = TestClient(app)
    assert c.post("/api/demo/reset").status_code == 200
    t = c.post(f"/api/estates/{EID}/conversations", json={"title": "q", "text": "What do the project documents say about CAL03 Opex?"}).json()["turns"][0]
    assert t["kind"] == "documents"
    b = next(x for x in t["blocks"] if x["type"] == "object_documents")
    assert b["object"] == "CAL03 Opex" and b["named_in"].startswith("named in ") and len(b["sections"]) >= 3
    assert all(s["citation"] and s["document"] and isinstance(s["names"], list) for s in b["sections"])
    assert t["blocks"][0]["type"] == "beyond" and t["blocks"][0]["documents"]
