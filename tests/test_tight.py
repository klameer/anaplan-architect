"""Tight answers and what was read beyond the exports (Ops ARC-32, 2026-11-16).

An answer is drafted, then edited by one short model call that may only cut, then checked by the validator. The edit
is refused in code when it adds anything: a name, a figure, a quote, a citation id; or drops a citation the lead
rests on. Every answer carries one line saying what it read besides the exports."""
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect import edit, chat
from test_access import _B, _workspace, _no_real_backend      # noqa: F401

DRAFT = """## Brief

`CAL04 Margin.Margin %` is the divide, and it is kept as it is. The record says: "CAL04 Margin is the margin module." `{sid}` It holds 36 cells. Leave it alone.

## What does it read?

It reads the revenue and the cost of sales of the same module, and nothing outside it. """ + " ".join(["This sentence only fills the page and says nothing a builder needs."] * 22) + """

## What else is there?

""" + " ".join(["More words that restate the figure the page already draws."] * 10)

EDITED = """## Brief

`CAL04 Margin.Margin %` is the divide, and it is kept as it is. The record says: "CAL04 Margin is the margin module." `{sid}` Leave it alone.

## What does it read?

- The revenue and cost of sales of the same module, nothing outside it."""


class Scripted:
    """search_documents, get_section, a long draft; and, asked to edit, whatever `edited` says."""
    def __init__(self, edited=EDITED, draft=DRAFT):
        self.messages = self; self.calls = 0; self.edits = 0; self.edited, self.draft = edited, draft; self.sid = None; self.edit_request = ""

    def create(self, **kw):
        self.calls += 1
        usage = _B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        system = kw.get("system")
        sys_text = system if isinstance(system, str) else " ".join(b.get("text", "") for b in system or [])
        if "You are the editor" in sys_text:
            self.edits += 1; self.edit_request = kw["messages"][-1]["content"]
            return _B(content=[_B(type="text", text=self.edited.format(sid=self.sid))], usage=usage)
        last = kw["messages"][-1]
        results = last["content"] if isinstance(last["content"], list) and last["content"] and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result" else None
        if results is None:
            if "no documents" in str(last["content"]):
                return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="get_object", input={"name": "CAL04 Margin.Margin %"})], usage=usage)
            return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="search_documents", input={"query": "margin module"})], usage=usage)
        text = " ".join(str(r.get("content")) for r in results)
        if self.sid is None and "no documents" not in str(kw["messages"]):
            m = re.search(r"s-[0-9a-f]{10}", text)
            if m:
                self.sid = m.group(0)
                return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="get_section", input={"section": self.sid})], usage=usage)
        if self.sid is None:
            return _B(content=[_B(type="text", text="## Brief\n\n`CAL04 Margin.Margin %` is the divide.")], usage=usage)
        return _B(content=[_B(type="text", text=self.draft.format(sid=self.sid))], usage=usage)


def _app(tmp_path, model):
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    c = TestClient(app)
    eid = _workspace(c, "Margins")
    assert c.post(f"/api/estates/{eid}/documents", files=[("files", ("Design note.md", b"# Design note\n\n## Margin\n\nCAL04 Margin is the margin module. It was built first.", "text/markdown"))]).status_code == 200
    return app, c, eid


def test_the_guard_lets_a_cut_through_and_refuses_anything_added():
    d = DRAFT.format(sid="s-0123456789")
    ok = EDITED.format(sid="s-0123456789")
    assert edit.refused(d, ok) is None and edit.prose_words(ok) < edit.prose_words(d)
    assert "name" in edit.refused(d, ok + "\n- Also see `CAL09 Invented.Thing`.")
    assert "figure" in edit.refused(d, ok + "\n- It holds 4,812 cells.")
    assert "quote" in edit.refused(d, ok.replace("is the margin module", "is the main margin module"))
    assert "citation" in edit.refused(d, ok.replace(' "CAL04 Margin is the margin module." `s-0123456789`', ""))
    assert "longer" in edit.refused(ok, d) or edit.refused(ok, d)
    assert edit.refused(d, "") and edit.refused(d, "Sorry, I cannot do that.")
    # the words inside a quoted passage and its id are evidence, not prose
    assert edit.prose_words('## Brief\n\nIt is kept. "CAL04 Margin is the margin module." `s-0123456789`') == 4


def test_a_long_draft_is_edited_before_the_validator_and_the_edit_is_metered_and_shown(tmp_path):
    model = Scripted()
    app, c, eid = _app(tmp_path, model)
    spent = []
    r = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say about the margin module?"})
    t = r.json()["turns"][0]
    assert model.edits == 1 and "restate" not in t["a"] and "nothing outside it" in t["a"]
    assert t["edit"]["applied"] and t["edit"]["before"] > 250 > t["edit"]["after"] and edit.prose_words(t["a"]) == t["edit"]["after"]
    # the validator ran on the edited text: the quote is found in its section, the verdict is the edited answer's
    assert t["verification"]["quotes"] == {"checked": 1, "found": 1, "missing": [], "unchecked": 0} or t["verification"]["quotes"]["found"] == 1
    names = [s["name"] for s in t["run"]["steps"]]
    assert names.index("edit") == names.index("validator") - 1 and "→" in next(s["out"] for s in t["run"]["steps"] if s["name"] == "edit")
    # the editor was told the question, what the page draws, and given the draft; nothing else
    assert "what does the design note say" in model.edit_request and "filling" not in model.edit_request and "This sentence only fills" in model.edit_request
    # the follow-up sees the edited answer, not the draft
    sess = app.state.sessions[r.json()["id"]]
    assert "This sentence only fills" not in str(sess.messages[-1]["content"])
    assert t["run"]["model_calls"] == model.calls == 4


def test_an_edit_that_adds_something_is_thrown_away_and_the_draft_stands(tmp_path):
    model = Scripted(edited=EDITED + "\n- It feeds `CAL99 Made Up.Total`, 9,999 cells.")
    app, c, eid = _app(tmp_path, model)
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say about the margin module?"}).json()["turns"][0]
    assert model.edits == 1 and not t["edit"]["applied"] and "name" in t["edit"]["why"]
    assert "This sentence only fills" in t["a"] and "CAL99" not in t["a"]
    assert "draft kept" in next(s["out"] for s in t["run"]["steps"] if s["name"] == "edit")


def test_the_edit_is_skipped_for_a_short_answer_in_concise_mode_and_by_the_setting(tmp_path, monkeypatch):
    model = Scripted()
    app, c, eid = _app(tmp_path, model)
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say?", "mode": "concise"}).json()["turns"][0]
    assert model.edits == 0 and "edit" not in [s["name"] for s in t["run"]["steps"]]
    # a login's own setting
    assert c.put("/api/prefs", json={"edit_pass": False}).json()["edit_pass"] is False
    model.sid = None
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say about margin?"}).json()["turns"][0]
    assert model.edits == 0 and t.get("edit") is None
    assert c.put("/api/prefs", json={"edit_pass": True}).json()["edit_pass"] is True
    # the instance's setting
    monkeypatch.setenv("ARCHITECT_EDIT_PASS", "0")
    model.sid = None
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say about margins?"}).json()["turns"][0]
    assert model.edits == 0


def test_every_answer_says_what_it_read_beyond_the_exports(tmp_path):
    model = Scripted()
    app, c, eid = _app(tmp_path, model)
    assert c.post(f"/api/estates/{eid}/documents", files=[("files", ("Other note.md", b"# Other note\n\n## Stock\n\nNothing about margins here at all.", "text/markdown"))]).status_code == 200
    note = c.post(f"/api/estates/{eid}/notes", json={"title": "Margin is fine", "body": "CAL04 Margin.Margin % is correct; leave it.", "scopes": ["estate"]}).json()
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what does the design note say about the margin module?"}).json()["turns"][0]
    b = t["blocks"][0]
    assert b["type"] == "beyond" and b["of_documents"] == 2 and [d["title"] for d in b["documents"]] == ["Design note"] and b["documents"][0]["id"]
    assert [n["title"] for n in b["notes"]] == ["Margin is fine"] and b["notes"][0]["id"] == note["id"]
    assert b["line"] == "Read 1 of 2 documents and 1 owner note"
    # nothing but the exports
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "no documents: what is margin %?"}).json()["turns"][0]
    b = t["blocks"][0]
    assert b["type"] == "beyond" and b["documents"] == [] and "none of the 2 documents" in b["line"]
    assert edit.beyond_line(0, 0, 0) == "Read nothing beyond the exports" and edit.beyond_line(0, 6, 0) == "Read nothing beyond the exports: none of the 6 documents, no owner note"
    assert edit.beyond_line(2, 6, 3) == "Read 2 of 6 documents and 3 owner notes" and edit.beyond_line(0, 6, 1) == "Read 1 owner note; none of the 6 documents"


def test_the_instructions_set_the_shape():
    s = chat.CHAT_SYSTEM
    assert "at most three sentences" in s and "250 words" in s and "Never restate" in s
    assert "three to five sentences" not in s
