"""Several people on one instance at the same time (the Railway requirement, 2026-11-14): what the load check found,
one test each, and the load check itself in a short form. The long form is `tools/load_check.py`."""
import sys, pathlib, threading, time
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth, access
from test_access import Model, _B, _login, _workspace, _no_real_backend      # noqa: F401  (the fixture isolates these tests too)


def _two(tmp_path, model, monkeypatch=None, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    pa = admin.post("/api/admin/users", json={"username": "alice", "name": "Alice", "demo": False}).json()["password"]
    pb = admin.post("/api/admin/users", json={"username": "bob", "name": "Bob", "demo": False}).json()["password"]
    return app, admin, _login(app, "alice", pa), _login(app, "bob", pb)


def _rows(app, name):
    db = app.state.db
    return db.one("SELECT COUNT(*) AS n FROM spend WHERE user_id=(SELECT id FROM users WHERE email=?)", name)["n"]


def test_a_chat_picked_up_again_is_still_metered_and_to_the_login_that_asks(tmp_path):
    """The load check's first failure: every login's ledger had fewer rows than the model calls made for it. A chat that
    is rebuilt from the store (after a document upload, a restart, or once 32 others have been used since) came back
    without its meter, so its calls were neither counted nor stopped at the cap. And a chat's meter was bound to the
    login that opened it: a second member's question in it went on the first member's ledger."""
    model = Model()
    app, admin, alice, bob = _two(tmp_path, model)
    eid = _workspace(alice, "Alice's models")
    conv = alice.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    assert _rows(app, "alice") == 2
    # a document upload drops the live chats of the workspace: the next question rebuilds this one from the store
    assert alice.post(f"/api/estates/{eid}/documents", files=[("files", ("note.md", b"# Note\n\nCAL04 Margin is the margin module.", "text/markdown"))]).status_code == 200
    assert conv["id"] not in app.state.sessions
    assert alice.post(f"/api/conversations/{conv['id']}/messages", json={"text": "and again?"}).status_code == 200
    assert _rows(app, "alice") == 4, "the follow-up in a rebuilt chat is on the ledger"
    # over the cap, the rebuilt chat is stopped like any other
    uid = app.state.db.one("SELECT id FROM users WHERE email='alice'")["id"]
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": 0.0001})
    app.state.sessions.clear()
    calls = model.calls
    r = alice.post(f"/api/conversations/{conv['id']}/messages", json={"text": "once more?"})
    assert r.status_code == 402 and model.calls == calls
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": None})
    # bob is let into the workspace and asks in alice's chat: it is bob's spend
    access.add_member(app.state.db, eid, app.state.db.one("SELECT id FROM users WHERE email='bob'")["id"])
    assert bob.post(f"/api/conversations/{conv['id']}/messages", json={"text": "bob asks"}).status_code == 200
    assert _rows(app, "bob") == 2 and _rows(app, "alice") == 4


class Slow(Model):
    """Holds every call until released, so a test can ask while an answer is in flight."""
    def __init__(self):
        super().__init__(); self.go = threading.Event(); self.started = threading.Event()

    def create(self, **kw):
        self.started.set(); self.go.wait(20)
        return super().create(**kw)


def test_a_login_has_a_limit_of_questions_in_flight_and_is_told_so(tmp_path, monkeypatch):
    """Each answer holds a worker thread while the model writes. One login asking in many chats at once could hold them
    all and leave nobody able to open a page: a login may have two answers in flight (ARCHITECT_MAX_CHATS_PER_LOGIN),
    the instance sixteen (ARCHITECT_MAX_CHATS), and the one over the limit is told to wait, in words."""
    model = Slow()
    app, admin, alice, bob = _two(tmp_path, model, monkeypatch, ARCHITECT_MAX_CHATS_PER_LOGIN="1", ARCHITECT_MAX_CHATS="2")
    ea, eb = _workspace(alice, "Alice's models"), _workspace(bob, "Bob's models")
    chats = [alice.post(f"/api/estates/{ea}/conversations", json={"title": f"q{i}"}).json()["id"] for i in range(2)]
    out = {}
    t = threading.Thread(target=lambda: out.update(first=alice.post(f"/api/conversations/{chats[0]}/messages", json={"text": "one"})))
    t.start(); assert model.started.wait(10)
    r = alice.post(f"/api/conversations/{chats[1]}/messages", json={"text": "two"})
    assert r.status_code == 429 and "already" in r.json()["detail"] and "wait" in r.json()["detail"].lower()
    r = alice.post(f"/api/conversations/{chats[1]}/stream", json={"text": "two"})
    assert r.status_code == 429
    # bob is not held up by alice's limit
    tb = threading.Thread(target=lambda: out.update(bob=bob.post(f"/api/estates/{eb}/conversations", json={"title": "b", "text": "what is margin %?"})))
    tb.start(); time.sleep(0.5)
    model.go.set(); t.join(20); tb.join(20)
    assert out["first"].status_code == 200 and out["bob"].status_code == 200
    # and once the answer is back, alice may ask again
    assert alice.post(f"/api/conversations/{chats[1]}/messages", json={"text": "two"}).status_code == 200
    assert app.state.in_flight == {"total": 0, "by_login": {}}


class RateLimited(Model):
    def create(self, **kw):
        e = RuntimeError("Error code: 429 - {'error': {'message': 'Rate limit reached for requests', 'type': 'rate_limit_error'}}")
        e.status_code = 429
        raise e


def test_a_provider_rate_limit_is_said_in_words(tmp_path):
    """What the person who hit a provider's rate limit saw was the provider's raw error. It is now one plain sentence
    that says whose limit it is and what to do; the raw text stays out of the answer."""
    app, admin, alice, bob = _two(tmp_path, RateLimited())
    eid = _workspace(alice, "Alice's models")
    cid = alice.post(f"/api/estates/{eid}/conversations", json={"title": "q"}).json()["id"]
    r = alice.post(f"/api/conversations/{cid}/messages", json={"text": "what is margin %?"})
    assert r.status_code == 503 and "rate limit" in r.json()["detail"] and "try again" in r.json()["detail"] and "{" not in r.json()["detail"]
    r = alice.post(f"/api/conversations/{cid}/stream", json={"text": "what is margin %?"})
    assert r.status_code == 200 and "rate limit" in r.text and "Error code" not in r.text and "rate_limit_error" not in r.text


def test_exports_are_read_a_few_at_a_time_and_the_rest_are_told_to_try_again(tmp_path, monkeypatch):
    """Reading exports is the heavy thing: each read is a process and holds the files in memory. Two may run at once
    (ARCHITECT_MAX_EXPORT_READS); an upload that cannot start within the wait is answered 429 in words, and nothing of
    it is left behind."""
    app, admin, alice, bob = _two(tmp_path, Model(), monkeypatch, ARCHITECT_MAX_EXPORT_READS="1", ARCHITECT_EXPORT_WAIT_S="0.3")
    snaps = app.state.snaps
    real, hold, started = snaps.process, threading.Event(), threading.Event()

    def slow(*a, **kw):
        started.set(); hold.wait(20)
        return real(*a, **kw)
    monkeypatch.setattr(snaps, "process", slow)
    out = {}
    t = threading.Thread(target=lambda: out.update(a=_workspace(alice, "Alice's models")))
    t.start(); assert started.wait(10)
    li = (pathlib.Path(__file__).parent / "fixtures" / "estate" / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    r = bob.post("/api/estates", data={"name": "Bob's models", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))])
    assert r.status_code == 429 and "try again" in r.json()["detail"] and r.headers.get("retry-after")
    assert bob.get("/api/estates").json() == []
    hold.set(); t.join(30)
    assert out["a"] and len(alice.get("/api/estates").json()) == 1
    assert bob.post("/api/estates", data={"name": "Bob's models", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).status_code == 200


def test_reading_exports_does_not_stop_the_server_answering_others(tmp_path, monkeypatch):
    """The upload routes were coroutines that read the exports on the event loop: while one person's exports were being
    read (seconds, for a real model) nobody else got an answer to anything, sign-in included. The load check timed a
    sign-in at eleven seconds. They run on worker threads now."""
    app, admin, alice, bob = _two(tmp_path, Model())
    snaps = app.state.snaps
    real, started = snaps.process, threading.Event()

    def slow(*a, **kw):
        started.set(); time.sleep(2.0)
        return real(*a, **kw)
    monkeypatch.setattr(snaps, "process", slow)
    li = (pathlib.Path(__file__).parent / "fixtures" / "estate" / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    with TestClient(app) as c:                                  # one event loop for every request made through it, as on a server
        c.cookies.update(alice.cookies); c.headers.update({"x-csrf": alice.cookies.get("csrf")})
        t = threading.Thread(target=lambda: c.post("/api/estates", data={"name": "A", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]))
        t.start(); assert started.wait(10)
        t0 = time.time()
        assert c.get("/health").status_code == 200 and c.get("/api/auth/me").status_code == 200
        took = time.time() - t0
        t.join(30)
    assert took < 1.0, f"/health and /api/auth/me took {took:.1f}s while exports were being read"


def test_several_logins_at_once_short():
    """The load check, short: four logins, two workspaces each, a real server process and a made-up model, everything
    at once for a quarter of a minute. No 5xx, no 'database is locked', nothing crosses between workspaces, one ledger
    row per model call, sign-in stays quick."""
    import load_check
    rep = load_check.run(logins=4, seconds=12, say=lambda *_: None)
    assert rep["failures"] == [], rep["failures"][:10]
    assert rep["questions_answered"] > 10 and rep["errors_5xx"] == 0


def test_two_people_uploading_the_same_file_at_once(tmp_path):
    """Found by the load check once uploads ran side by side: the store wrote every copy of a file through one
    temporary name made from its content, so two logins sending the same export at the same moment collided (a 500).
    Each write has its own temporary name now."""
    from anaplan_architect.orac.db import Db
    from anaplan_architect.orac.blobs import BlobStore
    blobs = BlobStore(tmp_path / "blobs", Db(tmp_path / "o.db"))
    errs = []
    for k in range(6):
        data, gate = bytes([k]) * (6 * 1024 * 1024), threading.Barrier(8)

        def put():
            try:
                gate.wait(10); blobs.put(data)
            except Exception as ex:
                errs.append(f"{type(ex).__name__}: {ex}")
        ts = [threading.Thread(target=put) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
    assert errs == [] and len(list((tmp_path / "blobs").rglob("*.part"))) == 0


def test_deleting_a_workspace_cannot_take_a_file_someone_else_is_uploading(tmp_path, monkeypatch):
    """Deleting a workspace clears the files nothing refers to. A file another login has just sent is written before
    its row says who refers to it; a delete landing in that moment took it, and that login's snapshot then had a file
    that was gone. Writing a file and recording who holds it is one step now, and the clear-out waits for it."""
    app, admin, alice, bob = _two(tmp_path, Model())
    blobs, snaps = app.state.blobs, app.state.snaps
    real = blobs.put

    def put_then_someone_deletes(data):
        sha = real(data)
        t = threading.Thread(target=blobs.gc); t.start(); t.join(0.7)       # another login's workspace delete, landing right here
        return sha
    monkeypatch.setattr(blobs, "put", put_then_someone_deletes)
    eid = _workspace(alice, "Alice's models")
    time.sleep(0.3)
    sid = alice.get(f"/api/estates/{eid}").json()["snapshot"]["id"]
    for f in app.state.db.q("SELECT blob_sha FROM snapshot_files WHERE snapshot_id=?", sid):
        assert blobs.exists(f["blob_sha"]), "the export alice uploaded is still in the store"
