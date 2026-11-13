"""Live sessions (review items 7 and 10): one answer at a time per conversation, idle sessions evicted and rebuilt from the
store, and the material every session caches following the workspace when a status or note changes under another session."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.store import Workspace
from anaplan_architect import chat, tools
from test_web import _Fake, _upload
from test_architect import _FakeClient, FX


def test_one_answer_at_a_time_and_idle_sessions_are_evicted(tmp_path, monkeypatch):
    from anaplan_architect import web as webmod
    monkeypatch.setattr(webmod, "SESSIONS_MAX", 2)
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    cids = [c.post(f"/api/estates/{eid}/conversations", json={"text": f"q{i}"}).json()["id"] for i in range(3)]
    assert list(app.state.sessions) == cids[1:]                              # the oldest idle session went
    s = app.state.sessions[cids[2]]
    assert s.lock.acquire(blocking=False)                                    # an answer in flight
    try:
        r = c.post(f"/api/conversations/{cids[2]}/messages", json={"text": "again"})
        assert r.status_code == 409 and "still answering" in r.json()["detail"]
        with c.stream("POST", f"/api/conversations/{cids[2]}/stream", json={"text": "again"}) as r2:
            assert r2.status_code == 409
    finally:
        s.lock.release()
    assert c.post(f"/api/conversations/{cids[2]}/messages", json={"text": "again"}).status_code == 200
    # the evicted conversation comes back from the store with its history, and evicts the next idle one
    r = c.post(f"/api/conversations/{cids[0]}/messages", json={"text": "back"})
    assert r.status_code == 200 and r.json()["a"].startswith("Turn 2")
    assert cids[0] in app.state.sessions and len(app.state.sessions) == 2
    assert c.get(f"/api/conversations/{cids[0]}").json()["turns"][1]["a"].startswith("Turn 2")


def test_material_follows_the_workspace_across_sessions(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    s1, s2 = chat.Session(w, client=_FakeClient()), chat.Session(w, client=_FakeClient())
    before = s2._system()[1]["text"]
    assert "[deliberate: guarded upstream]" not in before and "only shown where Revenue" not in before
    pid = next(p for p in w.index()["pattern"] if "F-HARDCODE" in p)[len("pattern:"):]
    tb = tools.Toolbox(w)
    assert "error" not in tb.set_status(pid, "deliberate", "guarded upstream")   # the chat tool of one session
    tb.remember("model:Caldergate Planning", "Margin % is only shown where Revenue is non-zero.")
    after = s2._system()[1]["text"]                                           # another session over the same workspace
    # a decision changes the material at once; a model note is counted there and handed with the questions it bears on (lean context, v0.2)
    assert "[deliberate: guarded upstream]" in after and "only shown where Revenue" not in after and "1 owner note about this model" in after
    assert s1._system()[1]["text"] == after
