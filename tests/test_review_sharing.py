"""Security review of workspace sharing (2026-11-24, at bf13414). One test per finding, written to fail first.
H1 notes across workspaces; M1 a shared workspace belongs to its team; M2 and M3 restore; M4 who asked; M5 tracing
consent; L1 to L5; and the three the reviewer suspected."""
import sys, pathlib, json, io, zipfile, threading, re
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth, telemetry
from test_access import _login, _workspace, _shared, _no_real_backend, _B, FX, GUARD_404      # noqa: F401


class Model:
    """One tool call, then an answer. `gate` holds the first call open; `during` runs once inside it."""
    def __init__(self): self.messages = self; self.calls = 0; self.gate = None; self.entered = threading.Event(); self.during = None

    def create(self, **kw):
        self.calls += 1
        usage = _B(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        last = kw["messages"][-1]
        if isinstance(last["content"], list) and isinstance(last["content"][0], dict) and last["content"][0].get("type") == "tool_result":
            return _B(content=[_B(type="text", text="## Brief\n\n`CAL04 Margin.Margin %` is the divide.")], usage=usage)
        if self.gate is not None:
            self.entered.set(); self.gate.wait(20)
        if self.during is not None:
            fn, self.during = self.during, None
            fn()
        return _B(content=[_B(type="tool_use", id=f"t{self.calls}", name="get_object", input={"name": "CAL04 Margin.Margin %"})], usage=usage)


def _setup(tmp_path, tracer=None, people=(("alice", "Acme"), ("amy", "Acme"), ("eve", "Acme"), ("bob", "Beta"))):
    model = Model()
    app = create_app(tmp_path / "data", client_factory=lambda: model, **({"tracer": tracer} if tracer else {}))
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    c = {"admin": _login(app, "admin", "correct horse battery")}
    ids, made = {}, set()
    for u, team in people:
        body = {"username": u, "name": u.title(), "demo": False}
        if team:
            body["team" if team in made else "new_team"] = team
            made.add(team)
        j = c["admin"].post("/api/admin/users", json=body).json()
        c[u] = _login(app, u, j["password"]); ids[u] = j["user"]["id"]
    return app, model, c, ids


@pytest.fixture()
def s(tmp_path):
    return _setup(tmp_path)


def _rezip(content, edit):
    z = zipfile.ZipFile(io.BytesIO(content)); buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as o:
        for n in z.namelist():
            o.writestr(n, edit(n, z.read(n)))
    return buf.getvalue()


def _restore(c, content, **data):
    return c.post("/api/estates/restore", files={"file": ("x.zip", content, "application/zip")}, data=data)


# ---------- H1 ----------
def test_h1_a_note_never_lists_another_workspaces_note_on_the_same_rule(s):
    app, model, c, ids = s
    b, a = _workspace(c["bob"], "Beta plan"), _workspace(c["alice"], "Acme")
    secret = "Beta will close the Leeds site in Q2"
    assert c["bob"].post(f"/api/estates/{b}/notes", json={"title": "BETA CONFIDENTIAL", "body": secret, "scopes": ["rule:R1"]}).status_code == 200
    r = c["alice"].post(f"/api/estates/{a}/notes", json={"title": "x", "body": "x", "scopes": ["rule:R1"]})
    n = r.json()
    assert r.status_code == 200 and n["siblings"] == [] and secret not in r.text and "BETA" not in r.text
    assert c["alice"].get(f"/api/notes/{n['id']}").json()["siblings"] == []
    assert c["alice"].patch(f"/api/notes/{n['id']}", json={"title": "y"}).json()["siblings"] == []
    # in one workspace the disagreement still surfaces
    m = c["alice"].post(f"/api/estates/{a}/notes", json={"title": "second", "body": "also R1", "scopes": ["rule:R1"]}).json()
    assert [x["title"] for x in m["siblings"]] == ["y"]


# ---------- M1 ----------
def test_m1_a_shared_workspace_stays_with_its_team_when_its_maker_leaves(s):
    app, model, c, ids = s
    admin, alice, amy, bob = c["admin"], c["alice"], c["amy"], c["bob"]
    e = _shared(alice, "Acme shared")
    assert amy.post(f"/api/estates/{e}/notes", json={"title": "Amy's", "body": "Acme margin target is 41%.", "scopes": ["estate"]}).status_code == 200
    assert admin.patch(f"/api/admin/users/{ids['alice']}", json={"team": "Beta"}).status_code == 200
    # the maker has left the team: she loses it like anyone else, and cannot hand it to her new team
    assert alice.get(f"/api/estates/{e}").status_code == 404 and alice.get(f"/api/estates/{e}/notes").status_code == 404
    assert alice.patch(f"/api/estates/{e}", json={"visibility": "shared"}).status_code == 404
    assert e not in [x["id"] for x in alice.get("/api/estates").json()]
    assert bob.get(f"/api/estates/{e}/notes").status_code == 404
    # it stays with the team it was shared with
    acc = amy.get(f"/api/estates/{e}").json()["access"]
    assert acc["visibility"] == "shared" and acc["team"] == "Acme" and acc["creator"] is None and acc["mine"] is False and "Alice" not in acc["members"]
    assert amy.patch(f"/api/estates/{e}", json={"visibility": "private"}).status_code == 403
    # the maker's role is the admin's until the admin names a team-mate: without reading it
    row = next(w for w in admin.get("/api/admin/workspaces").json()["workspaces"] if w["id"] == e)
    assert row["creator"] is None and row["team"] == "Acme" and admin.get(f"/api/estates/{e}").status_code == 404
    r = admin.patch(f"/api/admin/workspaces/{e}", json={"visibility": "private"})
    assert r.status_code == 400 and "maker" in r.json()["detail"]                 # private is one login's: there is none to give it to yet
    assert admin.patch(f"/api/admin/workspaces/{e}", json={"maker": ids["bob"]}).status_code == 400          # not a team-mate
    assert admin.patch(f"/api/admin/workspaces/{e}", json={"maker": ids["alice"]}).status_code == 400
    r = admin.patch(f"/api/admin/workspaces/{e}", json={"maker": ids["amy"]})
    assert r.status_code == 200 and r.json()["creator"] == "Amy"
    assert amy.get(f"/api/estates/{e}").json()["access"]["mine"] is True
    assert amy.patch(f"/api/estates/{e}", json={"visibility": "private"}).status_code == 200
    assert alice.get(f"/api/estates/{e}").status_code == 404 and c["eve"].get(f"/api/estates/{e}").status_code == 404
    # moved back, the old maker is a team-mate, not the maker
    assert amy.patch(f"/api/estates/{e}", json={"visibility": "shared"}).status_code == 200
    assert admin.patch(f"/api/admin/users/{ids['alice']}", json={"team": "Acme"}).status_code == 200
    assert alice.get(f"/api/estates/{e}").json()["access"]["mine"] is False
    # the admin can still delete one with no maker
    e2 = _shared(amy, "Second")
    assert admin.patch(f"/api/admin/users/{ids['amy']}", json={"team": None}).status_code == 200
    assert amy.get(f"/api/estates/{e2}").status_code == 404
    assert admin.request("DELETE", f"/api/estates/{e2}", json={"confirm": "Second"}).status_code == 200


def test_m1_a_workspace_with_other_peoples_content_is_never_shared_with_another_team(s):
    app, model, c, ids = s
    admin, alice, amy, bob = c["admin"], c["alice"], c["amy"], c["bob"]
    e = _shared(alice, "Acme shared")
    assert amy.post(f"/api/estates/{e}/notes", json={"title": "Amy's", "body": "Acme margin target is 41%.", "scopes": ["estate"]}).status_code == 200
    assert alice.patch(f"/api/estates/{e}", json={"visibility": "private"}).status_code == 200          # hers alone again
    assert admin.patch(f"/api/admin/users/{ids['alice']}", json={"team": "Beta"}).status_code == 200
    assert alice.get(f"/api/estates/{e}").status_code == 200                                              # a private workspace goes with its maker
    r = alice.patch(f"/api/estates/{e}", json={"visibility": "shared"})
    assert r.status_code == 400 and "Beta" in r.json()["detail"] and bob.get(f"/api/estates/{e}/notes").status_code == 404
    assert alice.get(f"/api/estates/{e}").json()["access"]["visibility"] == "private"
    # her own work, made after the move, she can share with the new team
    mine = _workspace(alice, "Alice's own")
    assert alice.patch(f"/api/estates/{mine}", json={"visibility": "shared"}).status_code == 200 and bob.get(f"/api/estates/{mine}").status_code == 200


# ---------- M2 ----------
def _forge_id(content, evil):
    def edit(n, d):
        if n == "manifest.json":
            m = json.loads(d); m["estate_id"] = evil; return json.dumps(m).encode()
        if n.startswith("tables/"):
            rows = json.loads(d)
            for r in rows:
                if n == "tables/estates.json":
                    r["id"] = evil
                elif "estate_id" in r:
                    r["estate_id"] = evil
            return json.dumps(rows).encode()
        return d
    return _rezip(content, edit)


def test_m2_a_restore_never_uses_an_id_from_the_archive_as_its_workspace_or_folder(s, tmp_path):
    app, model, c, ids = s
    alice, amy, eve = c["alice"], c["amy"], c["eve"]
    e = _shared(alice, "Acme shared")
    amy.post(f"/api/estates/{e}/conversations", json={"title": "Acme chat", "text": "AFTER-EVE-LEFT question"})
    tdir = tmp_path / "data" / "estates" / e / ".architect" / "transcripts"
    before = sorted(p.name for p in tdir.glob("*.jsonl"))
    assert before
    assert c["admin"].patch(f"/api/admin/users/{ids['eve']}", json={"team": None}).status_code == 200
    own = eve.post("/api/estates/create", json={"name": "eve empty"}).json()["id"]
    arch = eve.get(f"/api/estates/{own}/backup").content
    shape = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{16}$")
    # ids that are not in the shape this server makes are refused: case variants, trailing dots, route words
    for evil in (e.upper(), e + ".", e + " ", "create", "restore", "..", e + "/x", "CON", ""):
        r = _restore(eve, _forge_id(arch, evil), name="eve copy")
        assert r.status_code == 400, (evil, r.status_code, r.text[:200])
        assert (tmp_path / "data" / "estates" / e).is_dir() and sorted(p.name for p in tdir.glob("*.jsonl")) == before
    # the victim's exact id, and her own, restore under an id the server mints: never the archive's
    for claimed in (e, own):
        r = _restore(eve, _forge_id(arch, claimed), name="eve copy")
        assert r.status_code == 200, r.text[:300]
        new = r.json()["id"]
        assert new not in (e, own) and shape.match(new) and new.lower() != e.lower()
        z = zipfile.ZipFile(io.BytesIO(eve.get(f"/api/estates/{new}/backup").content))
        assert not [n for n in z.namelist() if n.startswith("architect/transcripts/")] and b"AFTER-EVE-LEFT" not in b"".join(z.read(n) for n in z.namelist())
        assert eve.request("DELETE", f"/api/estates/{new}", json={"confirm": "eve copy"}).status_code == 200
        assert sorted(p.name for p in tdir.glob("*.jsonl")) == before and amy.get(f"/api/estates/{e}").status_code == 200
    # no folder on disk differs from another only by case (what a case-insensitive disk would merge)
    names = [p.name for p in (tmp_path / "data" / "estates").iterdir()]
    assert len({n.lower() for n in names}) == len(names)
    # ids that become file names inside the workspace are held to the same shape
    real = _workspace(eve, "eve real")
    conv = eve.post(f"/api/estates/{real}/conversations", json={"title": "mine", "text": "what is margin %?"}).json()
    arch2 = eve.get(f"/api/estates/{real}/backup").content
    assert eve.request("DELETE", f"/api/estates/{real}", json={"confirm": "eve real"}).status_code == 200
    for bad in (conv["id"].upper(), conv["id"] + ".", "..", "a/b", "con"):
        forged = _rezip(arch2, lambda n, d: d.replace(conv["id"].encode(), bad.encode()) if n.startswith("tables/") else d)
        r = _restore(eve, forged)
        assert r.status_code == 400 and "shape" in r.json()["detail"], (bad, r.text[:200])
    # a transcript named for a device, or with a trailing dot, is not written anywhere
    odd = _rezip(arch2, lambda n, d: d)
    buf = io.BytesIO(odd)
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("architect/transcripts/NUL.jsonl", b"x")
    assert _restore(eve, buf.getvalue()).status_code == 400
    assert _restore(eve, arch2).status_code == 200


# ---------- M3 ----------
def test_m3_a_citation_id_resolves_inside_one_workspace_only(s):
    app, model, c, ids = s
    alice, amy, eve, db = c["alice"], c["amy"], c["eve"], s[0].state.db
    e = _shared(alice, "Acme shared")
    t = amy.post(f"/api/estates/{e}/conversations", json={"title": "old chat", "text": "what is margin %?"}).json()["turns"][0]
    X = t["citations"][0]["id"]
    assert eve.get(f"/api/citations/{X}").status_code == 200
    assert c["admin"].patch(f"/api/admin/users/{ids['eve']}", json={"team": None}).status_code == 200
    assert eve.get(f"/api/citations/{X}").json() == GUARD_404
    amy.post(f"/api/estates/{e}/conversations", json={"title": "SECRET: redundancy plan", "text": "what is margin %?"})
    own = _workspace(eve, "eve own")
    t2 = eve.post(f"/api/estates/{own}/conversations", json={"title": "mine", "text": "what is margin %?"}).json()["turns"][0]
    Y = t2["citations"][0]["id"]
    arch = eve.get(f"/api/estates/{own}/backup").content
    forged = _rezip(arch, lambda n, d: d.replace(Y.encode(), X.encode()) if n == "tables/citations.json" else d)
    assert eve.request("DELETE", f"/api/estates/{own}", json={"confirm": "eve own"}).status_code == 200
    r = _restore(eve, forged)
    # it restores, with an id of the server's making where the forged one was: the old workspace's id is not hers by claiming it
    assert r.status_code == 200 and "SECRET" not in r.text and "Acme" not in r.text and X not in r.text
    assert app.state.db.one("SELECT COUNT(*) AS n FROM citations WHERE id=?", X)["n"] == app.state.db.one(
        "SELECT COUNT(*) AS n FROM citations x JOIN turns t ON t.id=x.owner_id JOIN conversations c ON c.id=t.conversation_id WHERE x.id=? AND c.estate_id=?", X, e)["n"]
    assert eve.get(f"/api/citations/{X}").json() == GUARD_404 and amy.get(f"/api/citations/{X}").status_code == 200
    assert eve.request("DELETE", f"/api/estates/{r.json()['id']}", json={"confirm": "eve own"}).status_code == 200
    # defence in depth: the same id on a turn of her own, however it got into the store
    r = _restore(eve, arch)
    assert r.status_code == 200, r.text[:300]
    mine = r.json()["id"]
    turn = db.one("SELECT t.id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=?", mine)["id"]
    db.run("UPDATE citations SET id=? WHERE owner_kind='turn' AND owner_id=?", X, turn)
    for _ in range(3):
        j = eve.get(f"/api/citations/{X}")
        assert j.status_code == 200 and "SECRET" not in j.text and "old chat" not in j.text
        assert j.json()["estate"] == mine and {x["title"] for x in j.json()["cited_in"]["turns"]} == {"mine"}
        v = amy.get(f"/api/citations/{X}")                                          # and it still opens for the real members, from their own workspace
        assert v.status_code == 200 and v.json()["estate"] == e and {x["title"] for x in v.json()["cited_in"]["turns"]} == {"old chat", "SECRET: redundancy plan"}
    assert c["bob"].get(f"/api/citations/{X}").json() == GUARD_404


# ---------- M4 ----------
def test_m4_whoever_touches_a_busy_chat_does_not_take_over_who_asked_or_who_pays(s):
    app, model, c, ids = s
    alice, amy, db = c["alice"], c["amy"], s[0].state.db
    e = _shared(alice, "Acme shared")
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "t"}).json()["id"]
    spend = lambda u: db.one("SELECT COUNT(*) AS n FROM spend WHERE user_id=?", ids[u])["n"]
    assert spend("alice") == 0 and spend("amy") == 0
    for route in ("messages", "stream"):
        model.gate = threading.Event(); model.entered.clear(); out = {}
        t = threading.Thread(target=lambda: out.update(r=alice.post(f"/api/conversations/{cid}/messages", json={"text": "alice's question"})))
        t.start()
        assert model.entered.wait(20)
        r = amy.post(f"/api/conversations/{cid}/{route}", json={"text": "amy's question"})
        assert r.status_code == 409
        model.gate.set(); t.join(30); model.gate = None
        assert out["r"].status_code == 200 and out["r"].json()["by"] == ids["alice"]
        assert spend("amy") == 0 and spend("alice") > 0
    assert [x["by_name"] for x in alice.get(f"/api/conversations/{cid}").json()["turns"]] == ["Alice", "Alice"]
    # and each one's own question is still her own
    assert amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy's question"}).json()["by"] == ids["amy"] and spend("amy") == 2


# ---------- M5 ----------
def test_m5_a_members_content_tracing_never_sends_a_team_mates_earlier_question(tmp_path):
    from test_trace import FakeLangSmith
    ls = FakeLangSmith()
    app, model, c, ids = _setup(tmp_path, tracer=telemetry.Tracer(ls, host="stub", project="proj"))
    alice, amy = c["alice"], c["amy"]
    e = _shared(alice, "Acme shared")
    Q = "AMY-NEVER-CONSENTED question"
    cid = amy.post(f"/api/estates/{e}/conversations", json={"title": "chat", "text": Q}).json()["id"]
    assert amy.get("/api/auth/me").json()["trace"]["level"] == "off" and Q not in repr(ls.calls)
    assert alice.put("/api/prefs", json={"trace_level": "content"}).status_code == 200
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "ALICE-CONSENTED follow-up"}).status_code == 200
    sent = repr(ls.calls)
    assert "ALICE-CONSENTED" in sent and Q not in sent and "AMY-NEVER" not in sent
    # the same after the live session is gone and the chat is rebuilt from the store
    app.state.sessions.clear()
    n = len(ls.calls)
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "ALICE-AGAIN"}).status_code == 200
    later = repr(ls.calls[n:])
    assert "ALICE-AGAIN" in later and "ALICE-CONSENTED" in later and Q not in later


# ---------- L1 ----------
def test_l1_an_admin_is_in_no_team_and_cannot_share_someone_elses_workspace(s):
    app, model, c, ids = s
    admin, bob = c["admin"], c["bob"]
    e = _shared(c["alice"], "Acme shared")
    me = admin.get("/api/auth/me").json()["user"]["id"]
    r = admin.patch(f"/api/admin/users/{me}", json={"team": "Acme"})
    assert r.status_code == 400 and "admin" in r.json()["detail"] and admin.get(f"/api/estates/{e}/notes").status_code == 404
    assert admin.get("/api/estates").json() == []
    r = admin.patch(f"/api/admin/users/{ids['amy']}", json={"role": "owner"})          # a login in a team is not made an admin while it is in one
    assert r.status_code == 400 and c["amy"].get("/api/auth/me").json()["user"]["role"] == "member"
    p = _workspace(bob, "Bob private")
    r = admin.patch(f"/api/admin/workspaces/{p}", json={"visibility": "shared"})
    assert r.status_code == 400 and "maker" in r.json()["detail"]
    assert bob.get(f"/api/estates/{p}").json()["access"]["visibility"] == "private"
    # even a row written straight into the store does not let an admin in through a team
    app.state.db.run("UPDATE users SET team_id=(SELECT id FROM teams WHERE name='Acme') WHERE id=?", me)
    assert admin.get(f"/api/estates/{e}").status_code == 404


# ---------- L2 ----------
def test_l2_a_team_mate_adds_and_removes_only_what_they_added(s):
    app, model, c, ids = s
    alice, amy = c["alice"], c["amy"]
    e = _shared(alice, "Acme shared")
    doc = lambda who, name: who.post(f"/api/estates/{e}/documents", files=[("files", (name, b"# N\n\nText.", "text/markdown"))]).json()["results"][0]["document"]["id"]
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "alice chat", "text": "q"}).json()["id"]
    n = alice.post(f"/api/estates/{e}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    d = doc(alice, "alice.md")
    for r in (amy.delete(f"/api/conversations/{cid}"), amy.delete(f"/api/notes/{n}"), amy.delete(f"/api/documents/{d}"),
              amy.patch(f"/api/notes/{n}", json={"body": "rewritten"}), amy.post(f"/api/notes/{n}/supersede", json={}),
              amy.patch(f"/api/conversations/{cid}", json={"title": "renamed"}), amy.patch(f"/api/conversations/{cid}", json={"archived": True}),
              amy.patch(f"/api/estates/{e}", json={"name": "renamed by amy"}), amy.patch(f"/api/estates/{e}", json={"archived": True}),
              amy.get(f"/api/estates/{e}/backup"),
              amy.post(f"/api/estates/{e}/documents", data={"replaces": d}, files=[("files", ("alice.md", b"# N\n\nOther.", "text/markdown"))])):
        assert r.status_code == 403 and "Alice" in r.json()["detail"], (r.request.method, r.request.url.path, r.status_code, r.text[:120])
    s0 = alice.get(f"/api/estates/{e}").json()
    assert s0["name"] == "Acme shared" and not s0.get("archived") and alice.get(f"/api/notes/{n}").json()["body"] == "b"
    assert len(alice.get(f"/api/estates/{e}/documents").json()["documents"]) == 1 and alice.get(f"/api/conversations/{cid}").status_code == 200
    # she reads everything, asks in alice's chat, and adds and removes her own
    assert amy.post(f"/api/conversations/{cid}/messages", json={"text": "and why?"}).status_code == 200
    mc = amy.post(f"/api/estates/{e}/conversations", json={"title": "amy chat"}).json()["id"]
    mn = amy.post(f"/api/estates/{e}/notes", json={"title": "mine", "body": "b", "scopes": ["estate"]}).json()["id"]
    md = doc(amy, "amy.md")
    assert amy.patch(f"/api/notes/{mn}", json={"body": "edited"}).status_code == 200 and amy.patch(f"/api/conversations/{mc}", json={"title": "t2"}).status_code == 200
    assert amy.delete(f"/api/conversations/{mc}").status_code == 200 and amy.delete(f"/api/notes/{mn}").status_code == 200 and amy.delete(f"/api/documents/{md}").status_code == 200
    # the maker removes anything, renames, archives, backs up
    ac = amy.post(f"/api/estates/{e}/conversations", json={"title": "amy chat 2"}).json()["id"]
    assert alice.delete(f"/api/conversations/{ac}").status_code == 200 and alice.get(f"/api/estates/{e}/backup").status_code == 200
    assert alice.patch(f"/api/estates/{e}", json={"name": "Acme plan"}).json()["name"] == "Acme plan"
    # in a private workspace nothing changed
    p = _workspace(amy, "Amy's")
    assert amy.patch(f"/api/estates/{p}", json={"name": "Amy's 2"}).status_code == 200 and amy.get(f"/api/estates/{p}/backup").status_code == 200


# ---------- L3 ----------
def test_l3_nothing_says_whether_an_id_exists(s):
    app, model, c, ids = s
    alice, bob = c["alice"], c["bob"]
    e = _workspace(alice, "Acme private")
    conv = alice.post(f"/api/estates/{e}/conversations", json={"title": "t", "text": "what is margin %?"}).json()
    n = alice.post(f"/api/estates/{e}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    d = alice.post(f"/api/estates/{e}/documents", files=[("files", ("a.md", b"# N\n\nText.", "text/markdown"))]).json()["documents"][0]["id"]
    summ = alice.get(f"/api/estates/{e}").json()
    real = {"notes": n, "conversations": conv["id"], "documents": d, "models": summ["models"][0]["id"], "snapshots": summ["snapshot"]["id"],
            "turns": conv["turns"][0]["id"], "citations": conv["turns"][0]["citations"][0]["id"], "estates": e}
    tail = {"turns": "/plan"}
    for fam, ident in real.items():
        there = bob.get(f"/api/{fam}/{ident}{tail.get(fam, '')}")
        gone = bob.get(f"/api/{fam}/{fam[0]}-0000000000{tail.get(fam, '')}")
        assert there.status_code == gone.status_code == 404 and there.json() == gone.json() == GUARD_404, (fam, there.text, gone.text)
        for method in ("DELETE", "PATCH", "POST"):
            a, b = bob.request(method, f"/api/{fam}/{ident}", json={}), bob.request(method, f"/api/{fam}/{fam[0]}-0000000000", json={})
            assert (a.status_code, a.text) == (b.status_code, b.text), (method, fam, a.text, b.text)
    # a backup that claims someone's workspace id is told nothing about it
    own = bob.post("/api/estates/create", json={"name": "b"}).json()["id"]
    arch = bob.get(f"/api/estates/{own}/backup").content
    claims = _rezip(arch, lambda nme, dd: json.dumps(dict(json.loads(dd), estate_id=e)).encode() if nme == "manifest.json" else dd)
    fresh = _rezip(arch, lambda nme, dd: json.dumps(dict(json.loads(dd), estate_id="20200101-000000-0000000000000000")).encode() if nme == "manifest.json" else dd)
    a = bob.post("/api/estates/restore/inspect", files={"file": ("x.zip", claims, "application/zip")}).json()
    b = bob.post("/api/estates/restore/inspect", files={"file": ("x.zip", fresh, "application/zip")}).json()
    assert not a.get("conflict") and not b.get("conflict") and {k: v for k, v in a.items() if k != "estate_id"} == {k: v for k, v in b.items() if k != "estate_id"}
    # and somebody who is not signed in is not told how many workspaces there are
    h = TestClient(app).get("/health").json()
    assert h["status"] == "ok" and "estates" not in h


# ---------- L4 ----------
def test_l4_a_team_is_picked_from_the_list_and_a_new_one_is_its_own_action(s):
    app, model, c, ids = s
    admin = c["admin"]
    names = lambda: sorted(t["name"] for t in admin.get("/api/admin/teams").json()["teams"])
    assert names() == ["Acme", "Beta"]
    mk = lambda i, **kw: admin.post("/api/admin/users", json={"username": f"user{i}", "name": f"U{i}", "demo": False, **kw})
    # an existing team, however it is typed, is the same team
    for i, typed in enumerate(["ACME", "  acme  ", "Ac​me", "Ａcme", "acme "]):
        r = mk(i, team=typed)
        assert r.status_code == 200 and r.json()["user"]["team"] == "Acme", (typed, r.text)
    # a name that is not on the list makes nothing: a typo or a look-alike is refused, not turned into a company
    for i, typed in enumerate(["Acmee", "Аcme", 5, ["Acme"], {"name": "Acme"}, True], start=20):
        r = mk(i, team=typed)
        assert r.status_code == 400, (typed, r.text)
    assert names() == ["Acme", "Beta"]
    # a new team is asked for by name, once; the same name again in any spelling is refused
    assert admin.post("/api/admin/teams", json={"name": "  École  "}).json()["name"] == "École"
    for again in ("école", "ÉCOLE", "Acme", "acme​", "", "   ", 7, None, "Acсme"):
        assert admin.post("/api/admin/teams", json={"name": again}).status_code == 400, again
    assert mk(40, new_team="acme").status_code == 400 and mk(41, new_team="Gamma").json()["user"]["team"] == "Gamma"
    assert names() == ["Acme", "Beta", "Gamma", "École"] or names() == sorted(["Acme", "Beta", "Gamma", "École"])
    assert c["bob"].post("/api/admin/teams", json={"name": "Mine"}).status_code == 403
    assert mk(42, team="").json()["user"]["team"] is None and mk(43, team=None).json()["user"]["team"] is None


# ---------- L5 ----------
def test_l5_restored_content_is_the_restorers_with_the_original_author_as_text_only(s):
    app, model, c, ids = s
    alice, amy, bob, db = c["alice"], c["amy"], c["bob"], s[0].state.db
    e = _shared(alice, "Acme shared")
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "q", "text": "what is margin %?"}).json()["id"]
    amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy asks"})
    amy.post(f"/api/estates/{e}/notes", json={"title": "amy's", "body": "b", "scopes": ["estate"]})
    amy.post(f"/api/estates/{e}/documents", files=[("files", ("amy.md", b"# N\n\nText.", "text/markdown"))])
    arch = alice.get(f"/api/estates/{e}/backup").content
    assert alice.request("DELETE", f"/api/estates/{e}", json={"confirm": "Acme shared"}).status_code == 200
    # bob gets hold of the file and relabels a note as written by the admin
    admin_id = c["admin"].get("/api/auth/me").json()["user"]["id"]
    forged = _rezip(arch, lambda n, d: d.replace(ids["amy"].encode(), admin_id.encode()) if n == "tables/notes.json" else d)
    r = _restore(bob, forged, name="copy")
    assert r.status_code == 200, r.text[:300]
    new = r.json()["id"]
    for sql in ("SELECT author_id AS a FROM notes WHERE estate_id=?", "SELECT author_id AS a FROM conversations WHERE estate_id=?", "SELECT uploaded_by AS a FROM documents WHERE estate_id=?",
                "SELECT t.author_id AS a FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=?", "SELECT created_by AS a FROM estates WHERE id=?"):
        assert {x["a"] for x in db.q(sql, new)} == {ids["bob"]}, sql
    assert bob.get(f"/api/conversations/{cid}").json() == GUARD_404                 # the chat has an id of its own now
    conv = bob.get(f"/api/conversations/{bob.get(f'/api/estates/{new}/conversations').json()[0]['id']}").json()
    assert [t["by_name"] for t in conv["turns"]] == ["Bob", "Bob"] and [t["by_was"] for t in conv["turns"]] == ["Alice", "Amy"]
    note = bob.get(f"/api/estates/{new}/notes").json()[0]
    assert note["author_name"] == "Bob" and note["author_was"] in ("Amy", "Admin", None) and note["author_id"] == ids["bob"]
    assert bob.get(f"/api/estates/{new}/documents").json()["documents"][0]["uploaded_by_name"] == "Bob"
    assert db.one("SELECT COUNT(*) AS n FROM spend WHERE user_id=?", admin_id)["n"] == 0


# ---------- suspected ----------
def test_an_answer_under_way_stops_when_its_asker_loses_the_workspace(s):
    app, model, c, ids = s
    admin, alice, amy, db = c["admin"], c["alice"], c["amy"], s[0].state.db
    e = _shared(alice, "Acme shared")
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "t"}).json()["id"]
    turns = lambda: db.one("SELECT COUNT(*) AS n FROM turns WHERE conversation_id=?", cid)["n"]
    # moved out of the team between two model calls of one answer
    model.during = lambda: admin.patch(f"/api/admin/users/{ids['amy']}", json={"team": None})
    calls = model.calls
    r = amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy's last question"})
    assert r.status_code in (403, 404) and turns() == 0 and model.calls == calls + 1, (r.status_code, r.text[:200])
    assert admin.patch(f"/api/admin/users/{ids['amy']}", json={"team": "Acme"}).status_code == 200
    # the same on the stream: made private by its maker while a team-mate's answer is being written
    model.during = lambda: alice.patch(f"/api/estates/{e}", json={"visibility": "private"})
    calls = model.calls
    r = amy.post(f"/api/conversations/{cid}/stream", json={"text": "amy again"})
    assert r.status_code == 200 and '"type": "error"' in r.text and "CAL04" not in r.text and turns() == 0 and model.calls == calls + 1
    assert alice.patch(f"/api/estates/{e}", json={"visibility": "shared"}).status_code == 200
    # disabled mid-answer
    model.during = lambda: admin.patch(f"/api/admin/users/{ids['amy']}", json={"disabled": True})
    r = amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy once more"})
    assert r.status_code in (401, 403, 404) and turns() == 0
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "alice asks"}).status_code == 200 and turns() == 1


def test_nothing_in_an_archive_can_collide_with_or_block_what_is_in_the_store(s):
    """Third pass, 2026-11-24. Every id is made again on restore. So: a backup restores beside its original; an archive
    carrying somebody else's id says nothing about it and takes nothing from them; and an ex-member who restores an
    archive carrying one of the team's ids cannot make the team's own backup unrestorable."""
    app, model, c, ids = s
    alice, bob, db = c["alice"], c["bob"], s[0].state.db
    e = _workspace(alice, "Alice's")
    conv = alice.post(f"/api/estates/{e}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    note = alice.post(f"/api/estates/{e}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    arch = alice.get(f"/api/estates/{e}/backup").content
    r = _restore(alice, arch)                                   # the same backup while the workspace is still here
    assert r.status_code == 200 and r.json()["id"] != e and alice.get(f"/api/conversations/{conv['id']}").json()["estate"] == e
    own = _workspace(bob, "Bob's")
    bc = bob.post(f"/api/estates/{own}/conversations", json={"title": "q", "text": "what is margin %?"}).json()
    bnote = bob.post(f"/api/estates/{own}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    barch = bob.get(f"/api/estates/{own}/backup").content
    # an id of alice's in bob's archive, real or invented: the same answer, and nothing of alice's is touched or shown
    run = db.one("SELECT r.id FROM parse_runs r JOIN snapshots s ON s.id=r.snapshot_id WHERE s.estate_id=?", e)["id"]
    brun = json.loads(zipfile.ZipFile(io.BytesIO(barch)).read("tables/parse_runs.json"))[0]["id"]
    cite, bcite = conv["turns"][0]["citations"][0]["id"], bc["turns"][0]["citations"][0]["id"]
    seen = []
    for mine, theirs in ((bc["turns"][0]["id"], conv["turns"][0]["id"]), (bc["turns"][0]["id"], "t-0000000000"), (bc["id"], conv["id"]), (bc["id"], "c-0000000000"),
                         (bnote, note), (bnote, "n-0000000000"), (str(brun), str(run)), (bcite, cite)):
        r = _restore(bob, _rezip(barch, lambda n, d: d.replace(mine.encode(), theirs.encode()) if n.startswith("tables/") else d))
        seen.append(r.status_code)
        assert r.status_code == 200 and "Alice" not in r.text and theirs not in r.text, (theirs, r.status_code, r.text[:200])
    assert set(seen) == {200}
    assert alice.get(f"/api/conversations/{conv['id']}").json()["turns"][0]["a"] and alice.get(f"/api/notes/{note}").status_code == 200
    assert bob.get(f"/api/conversations/{conv['id']}").json() == GUARD_404 and bob.get(f"/api/citations/{cite}").json() == GUARD_404
    # and alice's own backup still restores after all of that
    assert _restore(alice, arch).status_code == 200


# ---------- not covered by the reviewer: looked at by the builder ----------
def test_a_tool_call_inside_a_chat_reads_its_own_workspace_only(s):
    """The chat tools take their workspace from the conversation. A model that asks for another workspace's document
    section, by its real id, is told there is none; and its note retrieval never returns another workspace's note."""
    app, model, c, ids = s
    alice, bob = c["alice"], c["bob"]
    a, b = _workspace(alice, "Acme"), _workspace(bob, "Beta")
    secret = "BETA-ONLY the Leeds site closes in Q2"
    bob.post(f"/api/estates/{b}/documents", files=[("files", ("beta.md", f"# Beta plan\n\n{secret}. CAL04 Margin is affected.".encode(), "text/markdown"))])
    bob.post(f"/api/estates/{b}/notes", json={"title": "beta note", "body": secret + " margin", "scopes": ["estate"]})
    sec = app.state.db.one("SELECT s.id FROM doc_sections s JOIN documents d ON d.id=s.document_id WHERE d.estate_id=?", b)["id"]
    seen = []

    class Asks:
        def __init__(self): self.messages = self; self.n = 0

        def create(self, **kw):
            self.n += 1
            seen.append(json.dumps(kw["messages"], default=str) + json.dumps(kw.get("system"), default=str))
            usage = _B(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0)
            calls = [("get_section", {"section": sec}), ("search_documents", {"query": "Leeds site closes"}), ("search_documents", {"query": "Beta plan", "document": "beta.md"})]
            if self.n <= len(calls):
                return _B(content=[_B(type="tool_use", id=f"t{self.n}", name=calls[self.n - 1][0], input=calls[self.n - 1][1])], usage=usage)
            return _B(content=[_B(type="text", text="Nothing found.")], usage=usage)
    app.state.client_factory = Asks
    r = alice.post(f"/api/estates/{a}/conversations", json={"title": "q", "text": "what does the Beta plan say about the Leeds site and margin?"})
    assert r.status_code == 200 and len(seen) == 4
    assert "BETA-ONLY" not in "".join(seen) and "BETA-ONLY" not in r.text and "beta.md" not in "".join(seen[1:]).replace('"document": "beta.md"', "")
    # names with markup in them come back as text the page escapes: the server-made report escapes them itself
    x = '<img src=x onerror=alert(1)><script>alert(2)</script>'
    assert c["admin"].post("/api/admin/teams", json={"name": x}).status_code == 200
    e = alice.post("/api/estates/create", json={"name": x}).json()["id"]
    page = alice.get("/app/")
    assert "script-src 'self'" in page.headers["content-security-policy"] and "unsafe-inline" not in page.headers["content-security-policy"].split("style-src")[0]
    rep = _workspace(alice, x)
    html = alice.get(f"/api/estates/{rep}/report").text
    assert "<script>alert(2)" not in html and "<img src=x" not in html
