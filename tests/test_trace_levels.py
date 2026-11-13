"""Tracing is decided per login, per turn, by whoever asked (Karim, 2026-11-13: "I don't want to capture other
people's information unless they are okay with it ... But I want to see everything that's going on for the queries
that I do").

Three levels: off, structure, content. An admin's turns are traced with content when a key is set. A non-admin's are
not traced at all, not even structure, unless that login turns it on for itself in Settings; nobody can turn it on for
another login. LANGSMITH_TRACE_CONTENT=0 is an instance-wide ceiling: nobody above structure."""
import sys, pathlib, json
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from fakes import FAKE_PT, FAKE_SK, FAKE_TR, FAKE_ANT
from anaplan_architect.orac import telemetry, auth
from test_web import _Fake, _upload
from test_trace import FakeLangSmith

ENV = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT", "LANGSMITH_TRACE_CONTENT", "ANTHROPIC_API_KEY", "ARCHITECT_NOTICE")
ADMIN_Q, MEMBER_Q = "what divides in the admin's own model?", "a member's private question about margin"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: []); monkeypatch.setattr(codex, "available", lambda: False)
    for k in ENV:
        monkeypatch.delenv(k, raising=False)


def _login(app, name, pw):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": name, "password": pw}).status_code == 200
    c.headers.update({"x-csrf": c.cookies.get("csrf")})
    return c


@pytest.fixture()
def traced(tmp_path):
    ls = FakeLangSmith()
    app = create_app(tmp_path / "data", client_factory=_Fake, tracer=telemetry.Tracer(ls, host="stub", project="proj"))
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    pw = admin.post("/api/admin/users", json={"username": "ann", "name": "Ann", "demo": False}).json()["password"]
    ann = _login(app, "ann", pw)
    return app, ls, admin, ann, _upload(admin, "Admin's").json()["id"], _upload(ann, "Ann's").json()["id"]


def _ask(c, eid, text, cid=None):
    if cid is None:
        r = c.post(f"/api/estates/{eid}/conversations", json={"title": text, "text": text})
        assert r.status_code == 200, r.text
        return r.json()["id"]
    assert c.post(f"/api/conversations/{cid}/messages", json={"text": text}).status_code == 200
    return cid


def test_a_non_admin_sends_nothing_until_they_turn_it_on_and_the_admin_sees_their_own_queries_whole(traced):
    app, ls, admin, ann, aeid, neid = traced
    # the admin's own question: the whole run tree, with content
    _ask(admin, aeid, ADMIN_Q)
    sent = repr(ls.calls)
    assert len(ls.created) >= 4 and ADMIN_Q in sent and "CAL04 Margin" in sent
    assert admin.get("/api/auth/me").json()["trace"] == {"available": True, "level": "content", "chosen": None, "chosen_at": None, "default": "content", "ceiling": "content"}
    # a non-admin's question: nothing leaves at all, not even structure; the in-app run timeline is still there
    before = len(ls.calls)
    cid = _ask(ann, neid, MEMBER_Q)
    assert len(ls.calls) == before and MEMBER_Q not in repr(ls.calls)
    t = ann.get(f"/api/conversations/{cid}").json()["turns"][0]
    assert t["run"]["steps"] and t["context"]["items"]
    me = ann.get("/api/auth/me").json()["trace"]
    assert me == {"available": True, "level": "off", "chosen": None, "chosen_at": None, "default": "off", "ceiling": "content"}
    # she turns structure on for herself: the next turn of the same chat is sent, as structure only
    r = ann.put("/api/prefs", json={"trace_level": "structure"})
    assert r.status_code == 200 and r.json()["trace_level"] == "structure" and r.json()["trace_level_at"]
    _ask(ann, neid, MEMBER_Q + " again", cid)
    mine = ls.calls[before:]
    assert len(mine) >= 4 and MEMBER_Q not in repr(mine) and "CAL04" not in repr(mine) and "Ann's" not in repr(mine)
    assert [kw["name"] for op, kw in mine if op == "create"][:2] == ["conversation", "turn 2"]
    # full content, by her own choice, from the turn after
    at = ann.put("/api/prefs", json={"trace_level": "content"}).json()["trace_level_at"]
    mark = len(ls.calls)
    _ask(ann, neid, "a third question she agreed to share", cid)
    assert "a third question she agreed to share" in repr(ls.calls[mark:])
    me = ann.get("/api/auth/me").json()["trace"]
    assert (me["level"], me["chosen"], me["chosen_at"]) == ("content", "content", at)
    # and off again: nothing more is sent (what was sent stays where it is)
    assert ann.put("/api/prefs", json={"trace_level": "off"}).json()["trace_level"] == "off"
    mark = len(ls.calls)
    _ask(ann, neid, "a fourth, private again", cid)
    assert len(ls.calls) == mark
    # a level that is not one of the three is refused
    assert ann.put("/api/prefs", json={"trace_level": "everything"}).status_code == 400


def test_nobody_sets_another_logins_level_and_the_admin_panel_only_shows_it(traced):
    app, ls, admin, ann, aeid, neid = traced
    uid = app.state.db.one("SELECT id FROM users WHERE email='ann'")["id"]
    r = admin.patch(f"/api/admin/users/{uid}", json={"trace_level": "content"})
    assert r.status_code == 400 and "their own" in r.json()["detail"]
    r = admin.post("/api/admin/users", json={"username": "raj", "name": "Raj", "demo": False, "trace_level": "content"})
    assert r.status_code == 400
    assert admin.put("/api/prefs", json={"trace_level": "content", "user": uid}).status_code == 200          # sets the admin's own, whatever else is in the body
    rows = {u["email"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert rows["ann"]["trace_level"] == "off" and rows["admin"]["trace_level"] == "content" and "raj" not in rows
    before = len(ls.calls)
    _ask(ann, neid, MEMBER_Q)
    assert len(ls.calls) == before
    # the admin panel follows her own choice, read-only
    ann.put("/api/prefs", json={"trace_level": "structure"})
    assert {u["email"]: u for u in admin.get("/api/admin/users").json()["users"]}["ann"]["trace_level"] == "structure"
    assert ann.get("/api/admin/users").status_code == 403


def test_a_document_summary_follows_the_uploaders_level(traced):
    app, ls, admin, ann, aeid, neid = traced
    app.state.summaries = True
    note = lambda name: [("files", (name, b"# Handover\n\nCAL04 Margin holds the margin. A private remark by the uploader.", "text/markdown"))]
    before = len(ls.calls)
    assert ann.post(f"/api/estates/{neid}/documents", files=note("anns.md")).json()["results"][0]["ok"]
    assert len(ls.calls) == before                                              # her summary was written by the model, and nothing was traced
    assert admin.post(f"/api/estates/{aeid}/documents", files=note("admins.md")).json()["results"][0]["ok"]
    mine = ls.calls[before:]
    assert any(kw.get("name") == "document summary" for op, kw in mine if op == "create") and "A private remark by the uploader" in repr(mine)
    ann.put("/api/prefs", json={"trace_level": "structure"})
    mark = len(ls.calls)
    assert ann.post(f"/api/estates/{neid}/documents", files=note("anns two.md")).json()["results"][0]["ok"]
    hers = ls.calls[mark:]
    assert any(kw.get("name") == "document summary" for op, kw in hers if op == "create") and "private remark" not in repr(hers) and "Handover" not in repr(hers)


def test_the_instance_ceiling_and_an_instance_with_no_key(tmp_path, monkeypatch):
    # LANGSMITH_TRACE_CONTENT=0: nobody above structure, the admin included, whatever they chose
    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_PT)
    monkeypatch.setenv("LANGSMITH_TRACE_CONTENT", "0")
    tracer = telemetry.Tracer.from_env(factory=FakeLangSmith)
    assert tracer.enabled and tracer.ceiling == "structure" and tracer.status()["ceiling"] == "structure"
    app = create_app(tmp_path / "capped", client_factory=_Fake, tracer=tracer)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    eid = _upload(admin).json()["id"]
    admin.put("/api/prefs", json={"trace_level": "content"})
    assert admin.get("/api/auth/me").json()["trace"]["level"] == "structure" and admin.get("/api/auth/me").json()["trace"]["ceiling"] == "structure"
    _ask(admin, eid, ADMIN_Q)
    assert len(tracer.client.calls) >= 4 and ADMIN_Q not in repr(tracer.client.calls)
    monkeypatch.delenv("LANGSMITH_TRACE_CONTENT")
    assert telemetry.Tracer.from_env(factory=FakeLangSmith).ceiling == "content"            # unset: no ceiling
    # no key: the setting is unavailable, choosing a level is refused with the reason, and asking works as ever
    app = create_app(tmp_path / "nokey", client_factory=_Fake, tracer=telemetry.Tracer(None))
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    eid = _upload(admin).json()["id"]
    assert admin.get("/api/auth/me").json()["trace"] == {"available": False, "level": "off", "chosen": None, "chosen_at": None, "default": "off", "ceiling": "content"}
    r = admin.put("/api/prefs", json={"trace_level": "content"})
    assert r.status_code == 400 and "not set up" in r.json()["detail"]
    assert admin.put("/api/prefs", json={"answer_mode": "concise"}).json()["answer_mode"] == "concise"
    _ask(admin, eid, ADMIN_Q)


def test_a_store_with_no_logins_traces_for_the_one_person_at_the_keyboard(tmp_path):
    """No logins, bound to localhost: the person asking is the person who set the key. Their turns are traced with content."""
    ls = FakeLangSmith()
    app = create_app(tmp_path / "data", client_factory=_Fake, tracer=telemetry.Tracer(ls, host="stub"))
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    assert c.get("/api/auth/me").json()["trace"]["level"] == "content"
    _ask(c, eid, ADMIN_Q)
    assert ADMIN_Q in repr(ls.calls)
    assert c.put("/api/prefs", json={"trace_level": "off"}).json()["trace_level"] == "off"
    mark = len(ls.calls)
    _ask(c, eid, "not this one")
    assert len(ls.calls) == mark


def test_a_tracing_only_key_is_accepted_and_masked(monkeypatch):
    """Karim's key (2026-11-13) is a tracing key: it may write runs and may read nothing, so the check at start-up, which
    lists projects, is refused with 403. That is a key that works, not one that was rejected. A 401 still is."""
    class TracingOnly(FakeLangSmith):
        def list_projects(self, limit=None):
            raise RuntimeError("Failed to GET /sessions in LangSmith API. HTTPError('403 Client Error: Forbidden', '{\"detail\":\"Permission projects:read is not allowed for tracing keys\"}')")
    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_TR)
    t = telemetry.Tracer.from_env(factory=TracingOnly)
    assert t.enabled and t.error is None and t.status()["write_only"] is True

    class Wrong(FakeLangSmith):
        def list_projects(self, limit=None):
            raise RuntimeError("Failed to GET /sessions in LangSmith API. HTTPError('401 Client Error: Unauthorized', '{\"detail\":\"Invalid token\"}')")
    t = telemetry.Tracer.from_env(factory=Wrong)
    assert not t.enabled and "did not accept the key" in t.error
    assert telemetry.mask("key " + FAKE_TR + " here") == "key [REDACTED_KEY] here"


def test_no_test_can_reach_a_real_tracer_or_read_the_machines_env_file(tmp_path, monkeypatch):
    """tests/conftest.py: found on 2026-11-13, when a real LangSmith key was put in this machine's .env. Test files
    that built the app without closing off .env would have traced their fixture turns to the real project."""
    import os
    from anaplan_architect import envfile
    from test_web import _Fake
    assert envfile.candidates() == [] and not os.environ.get("LANGSMITH_API_KEY") and not os.environ.get("LANGCHAIN_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY")
    # even with a .env holding a key in the working directory, an app built the plain way has no tracer
    (tmp_path / ".env").write_text("LANGSMITH_API_KEY=" + FAKE_TR + "\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    app = create_app(tmp_path / "data", client_factory=_Fake)
    assert app.state.tracer.enabled is False and not os.environ.get("LANGSMITH_API_KEY")
    # and the files that build the app carry no isolation of their own to forget: the suite's does it
    conftest = (pathlib.Path(__file__).parent / "conftest.py").read_text(encoding="utf-8")
    assert "autouse=True" in conftest and "candidates" in conftest and "LANGSMITH_API_KEY" in conftest
