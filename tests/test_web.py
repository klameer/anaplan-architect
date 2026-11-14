import sys, pathlib, json
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.store import Workspace
from anaplan_architect.questions import suggested

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


@pytest.fixture(autouse=True)
def _no_real_backend(monkeypatch):
    """Tests must not see this machine's .env, key or `codex login`: the fake client stands in and prices as Sonnet 5."""
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "CODEX_MODEL",
              "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT"):   # tests never trace to a real store
        monkeypatch.delenv(k, raising=False)


class _B:
    def __init__(self, **kw): self.__dict__.update(kw)


class _Fake:
    """Answers with one tool call then a citation, and remembers how many turns it has seen."""
    def __init__(self): self.messages = self; self.n = 0

    def create(self, **kw):
        self.n += 1
        last = kw["messages"][-1]
        if last["role"] == "user" and not (isinstance(last["content"], list) and last["content"] and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result"):
            return _B(content=[_B(type="tool_use", id=f"t{self.n}", name="list_models", input={})],
                      usage=_B(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=9000))
        # caching shape: material block carries the breakpoint; only the last message carries one
        assert kw["system"][1]["cache_control"]["type"] == "ephemeral" and "# The estate, in brief" in kw["system"][1]["text"]
        marked = [i for i, m in enumerate(kw["messages"]) if isinstance(m["content"], list) and any(isinstance(b, dict) and "cache_control" in b for b in m["content"])]
        assert marked == [len(kw["messages"]) - 1]
        user_turns = len([m for m in kw["messages"] if m["role"] == "user" and not (isinstance(m["content"], list) and m["content"] and isinstance(m["content"][0], dict) and m["content"][0].get("type") == "tool_result")])
        return _B(content=[_B(type="text", text=f"Turn {user_turns}: `CAL04 Margin.Margin %` is the divide. `Ghost.Nope` is not.")],
                  usage=_B(input_tokens=120, output_tokens=30, cache_read_input_tokens=9000, cache_creation_input_tokens=0))


class _Ev:
    def __init__(self, **kw): self.__dict__.update(kw)


class _FakeStream:
    """Streams the same script as _Fake through the SDK's stream shape."""
    def __init__(self, final): self.final = final

    def __enter__(self): return self

    def __exit__(self, *a): return False

    def __iter__(self):
        for b in self.final.content:
            if b.type == "tool_use":
                yield _Ev(type="content_block_start", content_block=_Ev(type="tool_use", name=b.name))
            else:
                for word in b.text.split(" "):
                    yield _Ev(type="content_block_delta", delta=_Ev(type="text_delta", text=word + " "))

    def get_final_message(self): return self.final


class _FakeStreaming(_Fake):
    def stream(self, **kw): return _FakeStream(self.create(**kw))


def test_stream_endpoint_emits_tool_text_done(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_FakeStreaming)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    cid = c.post(f"/api/estates/{eid}/conversations", json={"title": "streamed"}).json()["id"]
    with c.stream("POST", f"/api/conversations/{cid}/stream", json={"text": "go"}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(l[6:]) for l in r.iter_lines() if l.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "tool" and events[0]["name"] == "list_models" and "tool_result" in kinds and kinds[-1] == "done"
    assert "".join(e["delta"] for e in events if e["type"] == "text").strip().startswith("Turn 1")
    assert events[-1]["turn"]["a"].startswith("Turn 1") and events[-1]["turn"]["unverified"] == ["Ghost.Nope"]
    assert c.get(f"/api/conversations/{cid}").json()["turns"][0]["a"].startswith("Turn 1")


def settled(c, url, tries=240):
    """GET until the estate is not being re-read (a rename or a restore rebuilds the parse cache in the background)."""
    import time
    for _ in range(tries):
        r = c.get(url)
        if not (r.status_code == 409 and isinstance(r.json().get("detail"), dict) and r.json()["detail"].get("reparsing")):
            return r
        time.sleep(0.25)
    raise AssertionError("still re-reading after a minute")


def _upload(c, name="Test estate"):
    files, names = [], []
    for d in sorted(FX.iterdir()):
        files.append(("line_items", ("Line Items.csv", (d / "Line Items.csv").read_bytes(), "text/csv")))
        files.append(("actions", ("Actions.csv", (d / "Actions.csv").read_bytes(), "text/csv")))
        names.append(d.name.split(" ", 1)[1])
    return c.post("/api/estates", data={"name": name, "model_names": names}, files=files)


def test_questions_name_real_objects(tmp_path):
    w = Workspace.open(FX, tmp_path / "ws")
    qs = suggested(w)
    assert 5 <= len(qs) <= 10 and {q["kind"] for q in qs} >= {"design", "handover", "build"}
    idx = w.index()
    names = {n for s in idx.values() for n in s}
    assert any("CAL03 Opex" in q["text"] or "OUT01 Board Pack" in q["text"] or "Caldergate" in q["text"] for q in qs)


def test_upload_estate_and_converse(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    assert c.get("/").status_code == 200 and 'id="root"' in c.get("/").text
    assert c.get("/api/estates").json() == []
    r = _upload(c); assert r.status_code == 200, r.text
    s = r.json()
    assert [m["name"] for m in s["models"]] == ["Caldergate Planning", "Caldergate HR Model"] and s["llm"] and s["questions"]   # as typed, in upload order
    assert s["edges"] and s["edges"][0]["from"] == "Caldergate Planning"
    eid = s["id"]
    assert c.get("/api/estates").json()[0]["id"] == eid
    assert "Anaplan estate" in c.get(f"/api/estates/{eid}/report").text
    r = c.post(f"/api/estates/{eid}/conversations", json={"text": s["questions"][0]["text"]}); assert r.status_code == 200, r.text
    conv = r.json(); cid = conv["id"]
    t = conv["turns"][0]
    assert t["a"].startswith("Turn 1") and t["tools"][0]["tool"] == "list_models" and t["unverified"] == ["Ghost.Nope"]
    assert t["usage"]["calls"] == 2 and t["usage"]["cache_write"] == 9000 and t["usage"]["cache_read"] == 9000
    # Sonnet 5: 220 in * $2 + 50 out * $10 + 9000 cache read * $0.2 + 9000 cache write * $2.5 per MTok
    assert abs(t["usage"]["cost_usd"] - (220 * 2 + 50 * 10 + 9000 * 0.2 + 9000 * 4.0) / 1e6) < 1e-6
    t2 = c.post(f"/api/conversations/{cid}/messages", json={"text": "and then?"}).json()
    assert t2["a"].startswith("Turn 2")                         # the session remembered the first turn
    got = c.get(f"/api/conversations/{cid}").json(); assert len(got["turns"]) == 2
    assert c.get(f"/api/estates/{eid}").json()["conversations"][0]["turns"] == 2
    assert (tmp_path / "data" / "estates" / eid / ".architect" / "transcripts" / f"{cid}.jsonl").exists()
    # a restarted server lists the conversation from disk and continues it
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Fake))
    convs = c2.get(f"/api/estates/{eid}").json()["conversations"]
    assert [x["id"] for x in convs] == [cid] and convs[0]["turns"] == 2 and convs[0]["cost_usd"] > 0 and convs[0]["title"].startswith(s["questions"][0]["text"][:40])
    old = c2.get(f"/api/conversations/{cid}").json(); assert [t["a"][:6] for t in old["turns"]] == ["Turn 1", "Turn 2"] and old["turns"][0]["tools"][0]["tool"] == "list_models"
    t3 = c2.post(f"/api/conversations/{cid}/messages", json={"text": "still there?"}).json()
    assert t3["a"].startswith("Turn 3")


def test_no_key_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from anaplan_architect import envfile
    monkeypatch.setattr(envfile, "candidates", lambda: [])       # ignore any real .env on this machine
    from anaplan_architect import codex
    monkeypatch.setattr(codex, "available", lambda: False)        # and any real `codex login`
    c = TestClient(create_app(tmp_path / "data"))
    eid = _upload(c).json()["id"]
    r = c.post(f"/api/estates/{eid}/conversations", json={"text": "hi"})
    assert r.status_code == 503 and "No model is set up" in r.json()["detail"] and ".env.example" in r.json()["detail"]


def test_model_register_and_snapshot_flow(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    e = c.post("/api/estates/create", json={"name": "Staged"}).json()
    assert e["snapshot"] is None and e["models"] == [] and e["questions"] == []
    assert c.get(f"/api/estates/{e['id']}/report").status_code == 409
    m = c.post(f"/api/estates/{e['id']}/models", json={"name": "Caldergate HR", "purpose": "headcount", "owner": "Ana", "aliases": "Headcount Model; HR"}).json()
    assert m["aliases"] == ["HR", "Headcount Model"] and m["purpose"] == "headcount"
    assert c.post(f"/api/estates/{e['id']}/models", json={"name": "caldergate hr"}).status_code == 400
    plan, hr = FX / "1 Caldergate Planning", FX / "2 Caldergate HR Model"
    files = [("line_items", ("Line Items.csv", (hr / "Line Items.csv").read_bytes(), "text/csv")), ("actions", ("Actions.csv", (hr / "Actions.csv").read_bytes(), "text/csv")),
             ("line_items", ("Line Items.csv", (plan / "Line Items.csv").read_bytes(), "text/csv")), ("actions", ("Actions.csv", (plan / "Actions.csv").read_bytes(), "text/csv"))]
    r = c.post(f"/api/estates/{e['id']}/snapshots", data={"label": "first", "model_ids": [m["id"], ""], "model_names": ["", "Caldergate Planning"]}, files=files)
    assert r.status_code == 200, r.text
    snap = r.json(); sid = snap["id"]
    assert snap["status"] == "draft" and len(snap["files"]) == 4 and snap["ready"] == []
    assert [x["name"] for x in c.get(f"/api/estates/{e['id']}/models").json()] == ["Caldergate HR", "Caldergate Planning"]
    assert c.post(f"/api/snapshots/{sid}/activate").status_code == 409                       # not processed yet
    r = c.post(f"/api/snapshots/{sid}/process")
    assert r.status_code == 200 and r.json()["run"]["status"] in ("running", "ok")
    app.state.jobs.wait(sid)
    got = c.get(f"/api/snapshots/{sid}").json()
    assert got["status"] == "processed" and got["run"]["status"] == "ok" and set(got["run"]["coverage"]) == {"Caldergate HR", "Caldergate Planning"}
    s = c.post(f"/api/snapshots/{sid}/activate").json()
    assert s["snapshot"]["id"] == sid and s["questions"] and s["edges"][0]["from"] == "Caldergate Planning"
    assert s["models"][0]["files"]["line_items"]["uploaded_at"] and s["models"][0]["coverage"]["parse_rate"] == 1.0 and s["models"][0]["modules"]
    # a broken refresh of one model cannot be processed and the active snapshot keeps serving
    r = c.post(f"/api/estates/{e['id']}/snapshots", data={"label": "broken", "model_ids": [m["id"]]}, files=[("line_items", ("Line Items.csv", b"Module,Name\nA,B\n", "text/csv"))])
    bad = r.json()
    assert len(bad["files"]) == 4 and any(f["problem"] for f in bad["files"]) and bad["ready"]      # inherited the other three files
    assert c.post(f"/api/snapshots/{bad['id']}/process").status_code == 400
    assert c.get(f"/api/estates/{e['id']}").json()["snapshot"]["id"] == sid
    assert c.delete(f"/api/snapshots/{bad['id']}").status_code == 200 and c.delete(f"/api/snapshots/{sid}").status_code == 409
    assert c.patch(f"/api/models/{m['id']}", json={"purpose": "people planning"}).json()["purpose"] == "people planning"
    conv = c.post(f"/api/estates/{e['id']}/conversations", json={"title": "q"}).json()
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Fake))                   # restart: everything is still there
    assert c2.get(f"/api/conversations/{conv['id']}").json()["snapshot"] == sid
    again = c2.get(f"/api/estates/{e['id']}").json()
    assert again["snapshot"]["id"] == sid and [x["name"] for x in again["models"]] == ["Caldergate HR", "Caldergate Planning"] and again["models"][0]["purpose"] == "people planning"


def test_delete_conversation_moves_transcript_aside(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    keep = c.post(f"/api/estates/{eid}/conversations", json={"text": "keep me"}).json()["id"]
    gone = c.post(f"/api/estates/{eid}/conversations", json={"text": "drop me"}).json()["id"]
    assert {x["id"] for x in c.get(f"/api/estates/{eid}").json()["conversations"]} == {keep, gone}
    r = c.delete(f"/api/conversations/{gone}")
    assert r.status_code == 200 and r.json() == {"deleted": gone, "estate": eid}
    assert c.delete(f"/api/conversations/{gone}").status_code == 404 and c.get(f"/api/conversations/{gone}").status_code == 404
    assert [x["id"] for x in c.get(f"/api/estates/{eid}").json()["conversations"]] == [keep]
    t = tmp_path / "data" / "estates" / eid / ".architect" / "transcripts"
    assert not (t / f"{gone}.jsonl").exists() and (t / "deleted" / f"{gone}.jsonl").exists()
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Fake))                    # not listed after a restart either
    assert [x["id"] for x in c2.get(f"/api/estates/{eid}").json()["conversations"]] == [keep]


def test_health_and_delete_estate(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    eid = _upload(c).json()["id"]
    c.post(f"/api/estates/{eid}/conversations", json={"text": "hi"})
    assert c.request("DELETE", f"/api/estates/{eid}", json={"confirm": "wrong"}).status_code == 400
    assert c.request("DELETE", f"/api/estates/{eid}", json={"confirm": "Test estate"}).status_code == 200
    assert c.get(f"/api/estates/{eid}").status_code == 404 and c.get("/api/estates").json() == []
    assert not (tmp_path / "data" / "estates" / eid).exists()
    assert c.get("/api/estates?archived=true").json() == []


def test_turns_record_the_account_that_asked(tmp_path):
    """A conversation one member opens and another continues records each turn under the account that asked."""
    from anaplan_architect.orac import auth
    app = create_app(tmp_path / "data", client_factory=_Fake)
    owner = TestClient(app)
    eid = _upload(owner).json()["id"]
    auth.create_owner(app.state.db, app.state.workspace_id, "owner@example.com", "Owner", "correct horse battery")
    assert owner.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct horse battery"}).status_code == 200
    oc = {"x-csrf": owner.cookies.get("csrf")}
    from anaplan_architect.orac import access
    assert owner.get(f"/api/estates/{eid}").status_code == 200       # a workspace made before there were logins becomes the admin's on first use
    made = owner.post("/api/admin/users", json={"username": "guest@example.com", "name": "Guest", "password": "twelve characters", "demo": False}, headers=oc).json()
    access.add_member(app.state.db, eid, made["user"]["id"])          # the admin shares this one workspace with the second login
    guest = TestClient(app)
    assert guest.post("/api/auth/login", json={"email": "guest@example.com", "password": "twelve characters"}).status_code == 200
    gc = {"x-csrf": guest.cookies.get("csrf")}
    oid = owner.get("/api/auth/me").json()["user"]["id"]; gid = guest.get("/api/auth/me").json()["user"]["id"]
    conv = owner.post(f"/api/estates/{eid}/conversations", json={"text": "first"}, headers=oc).json()
    cid = conv["id"]
    assert conv["turns"][0]["by"] == oid
    assert guest.post(f"/api/conversations/{cid}/messages", json={"text": "second"}, headers=gc).json()["by"] == gid
    assert owner.post(f"/api/conversations/{cid}/messages", json={"text": "third"}, headers=oc).json()["by"] == oid
    assert [t["by"] for t in owner.get(f"/api/conversations/{cid}").json()["turns"]] == [oid, gid, oid]     # the store agrees
    turns = {a["id"]: a["questions"] for a in owner.get("/api/admin/users").json()["users"]}
    assert turns[oid] == 2 and turns[gid] == 1


def test_identity_setup_login_csrf_and_admin_made_logins(tmp_path):
    app = create_app(tmp_path / "data", client_factory=_Fake)
    c = TestClient(app)
    me = c.get("/api/auth/me").json()
    assert me["open"] is True and me["accounts"] is False and me["closed"] is False     # localhost, no accounts: open to this machine
    eid = _upload(c).json()["id"]                                                       # works with no cookies
    from anaplan_architect.orac import auth
    u = auth.create_owner(app.state.db, app.state.workspace_id, "Karim@Example.com", "Karim", "correct horse battery", "Northgate")   # the console path
    assert u["role"] == "owner"
    with pytest.raises(PermissionError):
        auth.create_owner(app.state.db, app.state.workspace_id, "x@y.z", "x", "another long one")                                  # only once
    assert c.get("/api/estates").status_code == 401                                     # the door shut the moment the owner existed
    r = c.post("/api/auth/login", json={"email": "karim@example.com", "password": "correct horse battery"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner" and r.json()["workspace"]["name"] == "Northgate" and r.json()["accounts"] is True
    # signed in: reads work; a mutating request needs the CSRF header that matches the cookie
    assert c.get(f"/api/estates/{eid}").status_code == 200
    assert c.post(f"/api/estates/{eid}/models", json={"name": "Extra"}).status_code == 403
    csrf = c.cookies.get("csrf")
    r = c.post(f"/api/estates/{eid}/models", json={"name": "Extra"}, headers={"x-csrf": csrf})
    assert r.status_code == 200 and r.json()["created_by"] == c.get("/api/auth/me").json()["user"]["id"]
    # a stranger gets 401 everywhere on /api except the auth routes and /health
    stranger = TestClient(app)
    assert stranger.get(f"/api/estates/{eid}").status_code == 401 and stranger.get("/api/estates").status_code == 401
    assert stranger.get("/health").status_code == 200 and stranger.get("/api/auth/me").json()["user"] is None
    assert stranger.post("/api/auth/login", json={"email": "karim@example.com", "password": "wrong password"}).status_code == 401
    assert stranger.get("/").status_code == 200                                    # the page itself loads and shows the sign-in
    # there is no signup and no invite: the admin creates the login and hands over the password, shown once
    assert stranger.post("/api/admin/users", json={"username": "guest"}).status_code == 401
    assert stranger.post("/api/auth/join", json={"code": "x", "email": "a@b.c", "name": "a", "password": "twelve characters"}).status_code in (401, 404, 405)
    made = c.post("/api/admin/users", json={"username": "Guest", "name": "Guest", "demo": False}, headers={"x-csrf": csrf}).json()
    pw = made["password"]
    assert made["user"]["role"] == "member" and made["user"]["email"] == "guest" and made["user"]["spend_cap_usd"] == 2.0 and len(pw) == 19
    assert stranger.post("/api/auth/login", json={"email": "guest", "password": pw}).status_code == 200
    guest_id = stranger.get("/api/auth/me").json()["user"]["id"]
    # a login sees only its own workspaces: the admin's is not there for the guest, by list or by id
    assert stranger.get("/api/estates").json() == [] and stranger.get(f"/api/estates/{eid}").status_code == 404
    assert stranger.post("/api/admin/users", json={"username": "another"}, headers={"x-csrf": stranger.cookies.get("csrf")}).status_code == 403
    assert stranger.get("/api/admin/users").status_code == 403
    rows = c.get("/api/admin/users").json()["users"]
    assert {a["email"] for a in rows} == {"karim@example.com", "guest"} and next(a for a in rows if a["id"] == guest_id)["sign_ins"] == 1
    assert c.patch(f"/api/admin/users/{guest_id}", json={"disabled": True}, headers={"x-csrf": csrf}).json()["user"]["disabled"] is True
    assert stranger.get("/api/estates").status_code == 401                        # sessions of a disabled login are gone
    assert stranger.post("/api/auth/login", json={"email": "guest", "password": pw}).status_code == 401
    # enabled again with a new password the admin resets: the old one no longer works
    r = c.patch(f"/api/admin/users/{guest_id}", json={"disabled": False, "reset_password": True}, headers={"x-csrf": csrf}).json()
    assert r["password"] != pw and stranger.post("/api/auth/login", json={"email": "guest", "password": pw}).status_code == 401
    assert stranger.post("/api/auth/login", json={"email": "guest", "password": r["password"]}).status_code == 200
    # password change signs the other sessions out; logout clears the cookie
    assert c.post("/api/auth/password", json={"old": "correct horse battery", "new": "an even longer one"}, headers={"x-csrf": csrf}).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["email"] == "karim@example.com"
    c.post("/api/auth/logout", headers={"x-csrf": c.cookies.get("csrf")})
    assert c.get("/api/auth/me").json()["user"] is None and c.get(f"/api/estates/{eid}").status_code == 401
    # everything survives a restart, and the server is no longer in setup mode
    c2 = TestClient(create_app(tmp_path / "data", client_factory=_Fake))
    assert c2.get("/api/auth/me").json()["accounts"] is True and c2.get("/api/estates").status_code == 401
    assert c2.post("/api/auth/login", json={"email": "karim@example.com", "password": "an even longer one"}).status_code == 200
    assert c2.get("/api/estates").status_code == 200


def test_network_bound_server_with_no_accounts_is_closed(tmp_path):
    c = TestClient(create_app(tmp_path / "data", client_factory=_Fake, host="0.0.0.0"))
    me = c.get("/api/auth/me").json()
    assert me["closed"] is True and me["open"] is False and "users create" in me["console_hint"]
    assert c.get("/api/estates").status_code == 503 and c.get("/").status_code == 200 and c.get("/health").status_code == 200


def test_users_cli_creates_the_admin_and_a_login(tmp_path, monkeypatch, capsys):
    import io
    from anaplan_architect import cli
    data = str(tmp_path / "data")
    monkeypatch.setattr("sys.stdin", io.StringIO("correct horse battery\n"))
    cli.main(["users", "create", "--data", data, "--owner", "--email", "owner@example.com", "--name", "Owner", "--workspace", "Northgate", "--password-stdin"])
    assert '"role": "owner"' in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO("twelve characters\n"))
    cli.main(["users", "create", "--data", data, "--email", "m@example.com", "--name", "M", "--password-stdin"])
    assert '"role": "member"' in capsys.readouterr().out
    cli.main(["users", "list", "--data", data])
    assert "owner@example.com" in capsys.readouterr().out
    c = TestClient(create_app(tmp_path / "data", client_factory=_Fake))
    assert c.get("/api/estates").status_code == 401
    assert c.post("/api/auth/login", json={"email": "m@example.com", "password": "twelve characters"}).status_code == 200
    assert c.get("/api/auth/me").json()["user"]["role"] == "member"
    with pytest.raises(SystemExit):
        cli.main(["users", "create", "--data", data, "--owner", "--email", "two@example.com", "--name", "Two", "--password-stdin"])   # a second owner is promoted, not created


def test_the_first_single_file_page_is_gone(tmp_path):
    """Review 2026-11-13, item 12: the v0.1 page (/legacy, a 40 KB static/index.html) is no longer shipped or served."""
    import anaplan_architect
    static = pathlib.Path(anaplan_architect.__file__).parent / "static"
    assert not (static / "index.html").exists() and (static / "app" / "index.html").exists()
    c = TestClient(create_app(tmp_path / "data", client_factory=lambda: None))
    assert c.get("/legacy").status_code == 404 and 'id="root"' in c.get("/").text and 'id="root"' in c.get("/app/").text
