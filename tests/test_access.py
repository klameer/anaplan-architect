"""v0.2 P5: two logins cannot see each other's workspaces, over every route the app has; the admin panel's numbers
are the store's numbers; a login over its spend cap is stopped before the model is called."""
import sys, pathlib, json, re
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth, access

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "ARCHITECT_DEFAULT_CAP_USD"):
        monkeypatch.delenv(k, raising=False)


class _B:
    def __init__(self, **kw): self.__dict__.update(kw)


class Model:
    """One tool call, then an answer that cites what it read. 1,000 tokens in and 200 out per call."""
    def __init__(self): self.messages = self; self.calls = 0

    def create(self, **kw):
        self.calls += 1
        usage = _B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        last = kw["messages"][-1]
        if isinstance(last["content"], list) and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result":
            return _B(content=[_B(type="text", text="## Brief\n\n`CAL04 Margin.Margin %` is the divide.")], usage=usage)
        return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="get_object", input={"name": "CAL04 Margin.Margin %"})], usage=usage)


def _login(app, username, password):
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": username, "password": password}).status_code == 200
    c.headers.update({"x-csrf": c.cookies.get("csrf")})
    return c


def _workspace(c, name):
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    return c.post("/api/estates", data={"name": name, "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()["id"]


@pytest.fixture()
def two(tmp_path):
    model = Model()
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    pa = admin.post("/api/admin/users", json={"username": "alice", "name": "Alice", "demo": False}).json()["password"]
    pb = admin.post("/api/admin/users", json={"username": "bob", "name": "Bob", "demo": False}).json()["password"]
    return app, admin, _login(app, "alice", pa), _login(app, "bob", pb), model


def test_two_logins_cannot_see_each_others_workspaces_over_every_route(two):
    app, admin, alice, bob, model = two
    eid = _workspace(alice, "Alice's models")
    bid = _workspace(bob, "Bob's models")
    # alice fills her workspace with one of everything that has an id
    conv = alice.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    turn = conv["turns"][0]
    doc = alice.post(f"/api/estates/{eid}/documents", files=[("files", ("note.md", b"# Note\n\nCAL04 Margin is the margin module.", "text/markdown"))]).json()["documents"][0]
    note = alice.post(f"/api/estates/{eid}/notes", json={"title": "n", "body": "a note", "scopes": ["estate"]}).json()
    s = alice.get(f"/api/estates/{eid}").json()
    ids = {"eid": eid, "cid": conv["id"], "sid": s["snapshot"]["id"], "mid": s["models"][0]["id"], "nid": note["id"], "did": doc["id"], "tid": turn["id"],
           "uid": "u-none", "pid": "p-none"}
    cite = next(x["id"] for x in turn["citations"])
    # each login lists only its own
    assert [e["id"] for e in alice.get("/api/estates").json()] == [eid] and [e["id"] for e in bob.get("/api/estates").json()] == [bid]
    assert admin.get("/api/estates").json() == []                       # the admin sees who did how much, never the workspaces themselves
    # every route of the app that carries an id: alice's ids, asked for by bob and by the admin, are not there
    checked, families = 0, set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or "{" not in path or path.startswith("/api/admin/"):
            continue
        params = re.findall(r"\{(\w+)\}", path)
        assert params[0] in ids or path.startswith("/api/citations/"), f"a route with an id the isolation test does not know: {path}"
        url = path
        for p in params:
            url = url.replace("{" + p + "}", cite if path.startswith("/api/citations/") else ids.get(p, "x"))
        scoped, found = access.estate_for(app.state.db, url)
        assert scoped and found == eid, f"the guard does not tie {path} to a workspace"
        families.add(path.split("/")[2])
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            for who in (bob, admin):
                r = who.request(method, url, json={}) if method in ("POST", "PUT", "PATCH", "DELETE") else who.request(method, url)
                if who is admin and method == "DELETE" and path == "/api/estates/{eid}":          # the one thing the admin may do to any workspace
                    assert r.status_code == 400 and "exact name" in r.json()["detail"]; continue
                assert r.status_code == 404 and r.json() == {"detail": "nothing here by that id"}, f"{method} {path} answered {r.status_code} to another login"
            checked += 1
    assert families == {"estates", "conversations", "snapshots", "models", "notes", "documents", "turns", "citations"} and checked >= 60
    # nothing of alice's was changed or removed by all that
    after = alice.get(f"/api/estates/{eid}").json()
    assert after["name"] == "Alice's models" and len(after["conversations"]) == 1 and after["documents"] == 1 and alice.get(f"/api/notes/{note['id']}").status_code == 200
    # and alice reaches every one of them herself
    for url in (f"/api/estates/{eid}", f"/api/conversations/{conv['id']}", f"/api/documents/{doc['id']}", f"/api/citations/{cite}", f"/api/snapshots/{ids['sid']}"):
        assert alice.get(url).status_code == 200, url
    # a chat tool cannot cross either: a section id from alice's workspace is nothing in bob's
    from anaplan_architect.orac import documents as docsmod
    sec = doc["sections"][0]["id"]
    assert docsmod.get_section(app.state.db, sec, bid) is None and docsmod.get_section(app.state.db, sec, eid) is not None
    assert docsmod.search(app.state.db, bid, "margin module")["hits"] == []
    # the demo is a copy per login
    da = alice.post("/api/demo/reset").json()["workspaces"]; db_ = bob.post("/api/demo/reset").json()["workspaces"]
    assert {w["id"] for w in da}.isdisjoint({w["id"] for w in db_}) and bob.get(f"/api/estates/{da[0]['id']}").status_code == 404
    assert len(alice.get("/api/estates").json()) == 3 and len(bob.get("/api/estates").json()) == 3


def test_the_admin_panel_matches_the_store_and_the_cap_trips(two):
    app, admin, alice, bob, model = two
    db = app.state.db
    eid = _workspace(alice, "Alice's models")
    for q in ("one", "two", "three"):
        r = alice.post(f"/api/estates/{eid}/conversations", json={"title": q, "text": q})
        assert r.status_code == 200
    alice.post(f"/api/estates/{eid}/documents", files=[("files", ("note.md", b"# Note\n\ntext", "text/markdown"))])
    panel = admin.get("/api/admin/users").json()
    row = {u["email"]: u for u in panel["users"]}
    a, b = row["alice"], row["bob"]
    uid = a["id"]
    # every figure on the panel is the same count made directly on the store
    assert a["questions"] == db.one("SELECT COUNT(*) AS n FROM turns WHERE author_id=?", uid)["n"] == 3
    assert a["chats"] == db.one("SELECT COUNT(*) AS n FROM conversations WHERE author_id=?", uid)["n"] == 3
    assert a["workspaces"] == db.one("SELECT COUNT(*) AS n FROM estate_members WHERE user_id=?", uid)["n"] == 1
    assert a["uploads"] == db.one("SELECT COUNT(*) AS n FROM snapshots WHERE created_by=?", uid)["n"] == 1 and a["documents"] == 1
    assert a["sign_ins"] == db.one("SELECT COUNT(*) AS n FROM audit WHERE action='user.login' AND user_id=?", uid)["n"] == 1
    assert a["metered_usd"] == round(db.one("SELECT SUM(metered_usd) AS s FROM turns WHERE author_id=?", uid)["s"], 4) > 0
    assert a["last_seen"] and a["spend_cap_usd"] == 2.0 and not a["over_cap"]
    assert (b["questions"], b["workspaces"], b["uploads"], b["metered_usd"]) == (0, 0, 0, 0)
    assert panel["totals"]["questions"] == 3 and panel["totals"]["logins"] == 3
    # the test client is priced as a flat-rate route would be: nothing billed, the metered amount still counted
    assert a["cost_usd"] == 0 or a["cost_usd"] == a["metered_usd"]
    # the admin lowers alice's cap below what she has used: her next question is refused before the model is called
    assert admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": round(a["metered_usd"] / 2, 4)}).json()["user"]["spend_cap_usd"] < a["metered_usd"]
    calls = model.calls
    r = alice.post(f"/api/estates/{eid}/conversations", json={"title": "four", "text": "four"})
    assert r.status_code == 402 and "spend cap" in r.json()["detail"]["message"] and model.calls == calls
    cid = alice.get(f"/api/estates/{eid}").json()["conversations"][0]["id"]
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "again"}).status_code == 402
    assert alice.post(f"/api/conversations/{cid}/stream", json={"text": "again"}).status_code == 402
    assert admin.get("/api/admin/users").json()["users"][1]["over_cap"] is True
    assert alice.get(f"/api/estates/{eid}").status_code == 200                       # reading is never capped
    # raised again (or removed), she can ask
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": None})
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "again"}).status_code == 200
    # a new login starts with the default cap; the admin has none
    assert row["admin"]["spend_cap_usd"] is None and admin.get("/api/admin/users").json()["default_cap_usd"] == 2.0


def test_deleting_a_workspace_members_and_the_admin_only(two):
    """A member deletes their own workspace with its name typed back; another login cannot; the admin can delete any.
    What went with it is gone: models, documents, chats, notes. The list says what each workspace holds."""
    app, admin, alice, bob, _model = two
    one, two = _workspace(alice, "Alice one"), _workspace(alice, "Alice two")
    alice.post(f"/api/estates/{one}/documents", files=[("files", ("note.md", b"# Note\n\nCAL04 Margin is the margin module.", "text/markdown"))])
    alice.post(f"/api/estates/{one}/notes", json={"title": "n", "body": "a note", "scopes": ["estate"]})
    alice.post(f"/api/estates/{one}/conversations", json={"title": "q"})
    row = next(e for e in alice.get("/api/estates").json() if e["id"] == one)
    assert (row["documents"], row["chats"], row["notes"], len(row["models"])) == (1, 1, 1, 1)
    # another login: the workspace does not exist; the wrong name: refused, nothing deleted
    assert bob.request("DELETE", f"/api/estates/{one}", json={"confirm": "Alice one"}).status_code == 404
    assert alice.request("DELETE", f"/api/estates/{one}", json={"confirm": "alice one"}).status_code == 400
    assert {e["id"] for e in alice.get("/api/estates").json()} == {one, two}
    # the member, with the name typed back
    assert alice.request("DELETE", f"/api/estates/{one}", json={"confirm": "Alice one"}).json()["deleted"] == one
    db = app.state.db
    for table in ("models", "documents", "conversations", "notes", "snapshots", "estate_members"):
        assert db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE estate_id=?", one)["n"] == 0, table
    assert alice.get(f"/api/estates/{one}").status_code == 404
    # the admin sees names and counts of every workspace, never content, and can delete any
    rows = admin.get("/api/admin/workspaces").json()["workspaces"]
    assert [(r["name"], r["members"], r["models"]) for r in rows] == [("Alice two", ["alice"], 1)]
    assert admin.get(f"/api/estates/{two}").status_code == 404 and bob.get("/api/admin/workspaces").status_code == 403
    assert admin.request("DELETE", f"/api/estates/{two}", json={"confirm": "Alice two"}).json()["deleted"] == two
    assert alice.get("/api/estates").json() == []          # the last one gone: the app lands on the empty state


def test_a_v01_store_keeps_every_login_in_its_workspaces_and_reading_never_writes(tmp_path):
    """Review 2026-11-13, item 9. A v0.1 store had logins and estates and no memberships: every login saw every estate.
    Upgrading must keep that (the admin and the other logins are members after the migration), and asking whether a
    login is a member must never write: a workspace does not go to whichever admin looks at it first."""
    import sqlite3
    from anaplan_architect.orac import access
    from anaplan_architect.orac.db import Db, MIGRATIONS
    data = tmp_path / "data"; data.mkdir()
    con = sqlite3.connect(data / "orac.db")
    for f in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if int(f.name[:3]) <= 9:
            con.executescript(f.read_text(encoding="utf-8"))
    con.execute("PRAGMA user_version = 9")
    con.execute("INSERT INTO workspaces(id, name, created) VALUES ('w-1', 'Team', '2026-09-01T00:00:00')")
    for uid, email, role in (("u-owner", "owner@example.com", "owner"), ("u-ann", "ann@example.com", "member"), ("u-raj", "raj@example.com", "member")):
        con.execute("INSERT INTO users(id, workspace_id, email, name, role, created) VALUES (?,?,?,?,?,?)", (uid, "w-1", email, email.split("@")[0], role, "2026-09-01T00:00:00"))
    for eid, by in (("e-one", "u-owner"), ("e-two", "u-ann")):
        con.execute("INSERT INTO estates(id, workspace_id, name, created_by, created) VALUES (?,?,?,?,?)", (eid, "w-1", eid, by, "2026-09-02T00:00:00"))
    con.commit(); con.close()
    db = Db(data / "orac.db")                                   # the upgrade
    assert db.version >= 10
    members = lambda eid: sorted(r["user_id"] for r in db.q("SELECT user_id FROM estate_members WHERE estate_id=?", eid))
    assert members("e-one") == members("e-two") == ["u-ann", "u-owner", "u-raj"]
    user = lambda uid: db.one("SELECT * FROM users WHERE id=?", uid)
    assert all(access.is_member(db, user(u), e) for u in ("u-owner", "u-ann", "u-raj") for e in ("e-one", "e-two"))
    # a workspace nobody is a member of: not the admin's for the asking, and asking leaves no row behind
    db.run("INSERT INTO estates(id, workspace_id, name, created) VALUES ('e-orphan', 'w-1', 'orphan', '2026-11-13T00:00:00')")
    assert access.is_member(db, user("u-owner"), "e-orphan") is False and access.visible(db, user("u-owner"), [{"id": "e-orphan"}]) == []
    assert members("e-orphan") == []
    # the first account made on a store that ran with no logins takes the workspaces made before it: once, when it is created
    data2 = tmp_path / "open"; app = create_app(data2, client_factory=lambda: None)
    eid = _workspace(TestClient(app), "Made with no login")
    d2 = app.state.db
    assert d2.one("SELECT COUNT(*) AS n FROM estate_members")["n"] == 0
    owner = auth.create_owner(d2, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    assert [r["user_id"] for r in d2.q("SELECT user_id FROM estate_members WHERE estate_id=?", eid)] == [owner["id"]]


def test_spend_is_a_ledger_deleting_gives_nothing_back_and_every_model_call_is_counted_and_gated(two):
    """Review 2026-11-13, item 4. Spend was summed from the answers still in the store, so deleting a chat or a
    workspace gave budget back; a turn that hit the tool-call limit recorded nothing; the summary written when a
    document is uploaded was neither checked nor counted; and the cap was looked at once, before a turn."""
    app, admin, alice, bob, model = two
    db = app.state.db
    eid = _workspace(alice, "Alice's models")
    uid = db.one("SELECT id FROM users WHERE email='alice'")["id"]
    spent = lambda: auth.spent(db, uid)
    rows = lambda kind="answer": db.one("SELECT COUNT(*) AS n FROM spend WHERE user_id=? AND kind=?", uid, kind)["n"]
    conv = alice.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    one = spent()
    assert one > 0 and model.calls == 2 and rows() == 2                       # one row per model call, not per answer
    panel = lambda: next(u for u in admin.get("/api/admin/users").json()["users"] if u["id"] == uid)
    assert panel()["metered_usd"] == one
    # deleting the chat, then the workspace, gives nothing back
    assert alice.delete(f"/api/conversations/{conv['id']}").status_code == 200 and spent() == one
    alice.post(f"/api/estates/{eid}/conversations", json={"title": "q2", "text": "and again?"})
    two_ = spent()
    assert two_ > one
    assert alice.request("DELETE", f"/api/estates/{eid}", json={"confirm": "Alice's models"}).status_code == 200
    assert spent() == two_ and panel()["metered_usd"] == two_ and panel()["questions"] == 0
    # a turn that ends on the tool-call limit has spent every call it made, and is kept
    eid = _workspace(alice, "Second")
    real = model.create
    def only_tools(**kw):
        model.calls += 1
        return _B(content=[_B(type="tool_use", id=f"t{model.calls}", name="get_object", input={"name": "CAL04 Margin.Margin %"})],
                  usage=_B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    model.create = only_tools
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": None})
    before, calls = spent(), model.calls
    t = alice.post(f"/api/estates/{eid}/conversations", json={"title": "loop", "text": "loop"}).json()["turns"]
    made = model.calls - calls
    assert made >= 2 and "too many tool calls" in t[0]["a"] and rows() == 4 + made and spent() > before
    # the cap is looked at before every model call: with room for one more call and no more, a turn is stopped after one
    model.create = real
    per_call = (spent() - before) / made
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": round(spent() + per_call * 0.5, 6)})
    calls = model.calls
    t = alice.post(f"/api/estates/{eid}/conversations", json={"title": "capped", "text": "what is margin %?"}).json()["turns"]
    assert model.calls == calls + 1 and "spend cap" in t[0]["a"]
    assert alice.post(f"/api/estates/{eid}/conversations", json={"title": "after", "text": "again"}).status_code == 402 and model.calls == calls + 1
    # the summary written when a document is uploaded is a model call: refused over the cap, counted under it
    app.state.summaries = True
    note = lambda name: [("files", (name, b"# Note\n\nCAL04 Margin is the margin module. It holds the margin.", "text/markdown"))]
    assert alice.post(f"/api/estates/{eid}/documents", files=note("over.md")).json()["results"][0]["ok"] and model.calls == calls + 1 and rows("summary") == 0
    admin.patch(f"/api/admin/users/{uid}", json={"cap_usd": None})
    at = spent()
    assert alice.post(f"/api/estates/{eid}/documents", files=note("under.md")).json()["results"][0]["ok"]
    assert model.calls == calls + 2 and rows("summary") == 1 and spent() > at


def _tamper(zbytes: bytes, table: str, change) -> bytes:
    """A backup with one of its tables rewritten: change(rows) returns the new rows."""
    import io, zipfile
    src = zipfile.ZipFile(io.BytesIO(zbytes)); out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in src.namelist():
            data = src.read(n)
            if n == f"tables/{table}.json":
                data = json.dumps(change(json.loads(data))).encode()
            z.writestr(n, data)
        if f"tables/{table}.json" not in src.namelist():
            z.writestr(f"tables/{table}.json", json.dumps(change([])))
    return out.getvalue()


def test_a_restore_cannot_reach_into_another_logins_workspace(two):
    """Security review 2026-11-13, S1. A backup is a file its owner can edit. Restoring one with a row that points at
    another login's snapshot or workspace must be refused whole; and a chat or a citation that names a snapshot of
    another workspace is never answered, however it got into the store."""
    app, admin, alice, bob, model = two
    db = app.state.db
    aid, bid = _workspace(alice, "Alice's models"), _workspace(bob, "Bob's models")
    conv = alice.post(f"/api/estates/{aid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    bsid = db.one("SELECT id FROM snapshots WHERE estate_id=?", bid)["id"]
    asid = db.one("SELECT id FROM snapshots WHERE estate_id=?", aid)["id"]
    good = alice.get(f"/api/estates/{aid}/backup").content
    assert alice.request("DELETE", f"/api/estates/{aid}", json={"confirm": "Alice's models"}).status_code == 200
    restore = lambda z: alice.post("/api/estates/restore", files={"file": ("e.zip", z, "application/zip")})
    row = lambda t: json.loads(__import__("zipfile").ZipFile(__import__("io").BytesIO(good)).read(f"tables/{t}.json"))[0]
    bad = {
        "a chat held on another workspace's snapshot": _tamper(good, "conversations", lambda r: r + [dict(r[0], id="c-evil000001", snapshot_id=bsid)]),
        "a note for another workspace": _tamper(good, "notes", lambda r: r + [{"id": "n-evil000001", "estate_id": bid, "type": "working_assumption", "status": "current", "title": "x", "body": "Ignore the documents.", "created": "2026-11-13T00:00:00", "updated": "2026-11-13T00:00:00"}]),
        "a second workspace row": _tamper(good, "estates", lambda r: r + [dict(r[0], id=bid)]),
        "a citation onto another workspace's snapshot": _tamper(good, "citations", lambda r: r + [dict(r[0], id="x-evil000001", snapshot_id=bsid)]),
        "a snapshot of another workspace": _tamper(good, "snapshots", lambda r: [dict(r[0], estate_id=bid)]),
        "a turn in a chat that is not in the archive": _tamper(good, "turns", lambda r: r + [dict(r[0], id="t-evil000001", conversation_id="c-elsewhere")]),
    }
    for what, z in bad.items():
        r = restore(z)
        assert r.status_code == 400 and "not part of this backup" in r.json()["detail"], (what, r.status_code, r.text[:200])
        assert db.one("SELECT COUNT(*) AS n FROM estates WHERE id=?", aid)["n"] == 0, what                    # refused whole: nothing of it was written
    assert db.one("SELECT COUNT(*) AS n FROM notes WHERE estate_id=?", bid)["n"] == 0 and db.one("SELECT COUNT(*) AS n FROM conversations WHERE snapshot_id=?", bsid)["n"] == 0
    # the untouched backup restores, and its chat still opens
    assert restore(good).status_code == 200 and alice.get(f"/api/conversations/{conv['id']}").status_code == 200
    # inspecting a backup that claims another login's workspace id says the id is taken, never whose it is or what it is called
    claims = _tamper(good, "estates", lambda r: [dict(r[0], id=bid)])
    import io as _io, zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(_io.BytesIO(claims)) as src, _zf.ZipFile(buf, "w") as z:
        for n in src.namelist():
            z.writestr(n, json.dumps(dict(json.loads(src.read(n)), estate_id=bid)) if n == "manifest.json" else src.read(n))
    seen = alice.post("/api/estates/restore/inspect", files={"file": ("e.zip", buf.getvalue(), "application/zip")})
    assert seen.status_code == 200 and "Bob's models" not in seen.text and seen.json()["conflict"] == {"id": bid}
    r = restore(buf.getvalue())
    assert r.status_code in (400, 409) and "Bob's models" not in r.text
    # defence in depth: rows as a restore before this fix could have left them
    calls = model.calls
    db.run("INSERT INTO conversations(id, estate_id, title, snapshot_id, author_id, created, updated) SELECT 'c-planted0001', ?, 'planted', ?, author_id, created, updated FROM conversations WHERE id=?", aid, bsid, conv["id"])
    r = alice.post("/api/conversations/c-planted0001/messages", json={"text": "what is in this model?"})
    assert r.status_code in (404, 409) and model.calls == calls, (r.status_code, r.text[:200])
    t = db.one("SELECT id FROM turns WHERE conversation_id=?", conv["id"])["id"]
    db.run("INSERT INTO citations(id, owner_kind, owner_id, provenance, snapshot_id, model_id, kind, object_ref, source_ref, payload_json) VALUES ('x-planted0001','turn',?,'observed',?,'Caldergate Planning','line_item','CAL04 Margin.Margin %','get_object','{}')", t, bsid)
    assert alice.get("/api/citations/x-planted0001").status_code == 404
    # new ids are not guessable from the clock
    from anaplan_architect.orac.db import new_id
    ids = {new_id() for _ in range(50)}
    assert len(ids) == 50 and all(len(i.rsplit("-", 1)[1]) >= 16 for i in ids)


def test_a_question_has_a_length_limit_and_the_document_limit_cannot_be_sidestepped(two):
    """Security review 2026-11-13, S2 (what the spend ledger did not already cover). A question of any length was
    sent to the model; and naming a document that does not exist as the one being replaced skipped the 20-document
    limit."""
    app, admin, alice, bob, model = two
    eid = _workspace(alice, "Alice's models")
    calls = model.calls
    long = "why " * 5000                                            # 20,000 characters
    r = alice.post(f"/api/estates/{eid}/conversations", json={"title": "long", "text": long})
    assert r.status_code == 400 and "characters" in r.json()["detail"] and model.calls == calls
    cid = alice.post(f"/api/estates/{eid}/conversations", json={"title": "ok"}).json()["id"]
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": long}).status_code == 400
    assert alice.post(f"/api/conversations/{cid}/stream", json={"text": long}).status_code == 400 and model.calls == calls
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "what is margin %?"}).status_code == 200
    # the document limit
    from anaplan_architect.orac import documents as docsmod
    note = lambda i: [("files", (f"note {i}.md", f"# Note {i}\n\nText {i}.".encode(), "text/markdown"))]
    for i in range(docsmod.MAX_DOCS):
        assert alice.post(f"/api/estates/{eid}/documents", files=note(i)).json()["results"][0]["ok"]
    over = alice.post(f"/api/estates/{eid}/documents", files=note("over")).json()["results"][0]
    assert not over["ok"] and "limit" in over["error"]
    bogus = alice.post(f"/api/estates/{eid}/documents", data={"replaces": "d-doesnotexist"}, files=note("bogus")).json()["results"][0]
    assert not bogus["ok"] and len(alice.get(f"/api/estates/{eid}/documents").json()["documents"]) == docsmod.MAX_DOCS
    # replacing a document that is there is still allowed at the limit, and does not add one
    did = alice.get(f"/api/estates/{eid}/documents").json()["documents"][0]["id"]
    assert alice.post(f"/api/estates/{eid}/documents", data={"replaces": did}, files=note("v2")).json()["results"][0]["ok"]
    assert len(alice.get(f"/api/estates/{eid}/documents").json()["documents"]) == docsmod.MAX_DOCS
    # a document id of another workspace is not "there" either
    other = _workspace(bob, "Bob's"); bdoc = bob.post(f"/api/estates/{other}/documents", files=note("b")).json()["results"][0]["document"]["id"]
    assert not alice.post(f"/api/estates/{eid}/documents", data={"replaces": bdoc}, files=note("x")).json()["results"][0]["ok"]


def test_a_note_cannot_borrow_a_citation_or_a_model_from_another_workspace(two):
    """Security review 2026-11-13, S7. Creating a note with another workspace's citation id copied that citation into
    the note and returned what it opens; a model id of another workspace was accepted and its name returned."""
    app, admin, alice, bob, model = two
    aid, bid = _workspace(alice, "Alice's models"), _workspace(bob, "Bob's models")
    conv = alice.post(f"/api/estates/{aid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    cite = conv["turns"][0]["citations"][0]["id"]
    amodel = alice.get(f"/api/estates/{aid}").json()["models"][0]["id"]
    db = app.state.db
    db.run("UPDATE models SET name='Alice Secret Model' WHERE id=?", amodel)
    r = bob.post(f"/api/estates/{bid}/notes", json={"body": "borrowing", "sources": [cite]})
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["sources_resolved"] == [] and n["sources_missing"] == [cite] and "Margin" not in json.dumps(n)          # it looks like an id that resolves to nothing
    assert db.one("SELECT COUNT(*) AS n FROM citations WHERE owner_kind='note' AND owner_id=?", n["id"])["n"] == 0
    r = bob.post(f"/api/estates/{bid}/notes", json={"body": "scoped elsewhere", "objects": [{"scope": "model", "model_id": amodel}]})
    assert r.status_code == 400 and "Alice Secret Model" not in r.text
    assert bob.patch(f"/api/notes/{n['id']}", json={"objects": [{"scope": "model", "model_id": amodel}]}).status_code == 400
    assert "Alice Secret Model" not in json.dumps(bob.get(f"/api/estates/{bid}/notes").json())
    # in her own workspace both still work
    mine = alice.post(f"/api/estates/{aid}/notes", json={"body": "mine", "sources": [cite], "objects": [{"scope": "model", "model_id": amodel}]}).json()
    assert [s["id"] for s in mine["sources_resolved"]] == [cite] and mine["objects"][0]["model"] == "Alice Secret Model"
