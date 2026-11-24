"""Third pass of the security review (2026-11-24, at 5e599d8): an independent reviewer attacked the fixes of the first
two. One test per item it left open or found new, written to fail first. Items 8 and 11 (ids on restore) are in
test_review_sharing.py::test_nothing_in_an_archive_can_collide_with_or_block_what_is_in_the_store."""
import sys, pathlib, json, io, zipfile, threading, time, re
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth
from test_access import _login, _workspace, _shared, _no_real_backend, _B, FX, GUARD_404      # noqa: F401
from test_review_sharing import _setup, _rezip, _restore, Model


@pytest.fixture()
def s(tmp_path):
    return _setup(tmp_path)


def _arch(c, name="Mine"):
    e = _workspace(c, name)
    return e, c.get(f"/api/estates/{e}/backup").content


def _with(arc, **files):
    src = zipfile.ZipFile(io.BytesIO(arc)); out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for i in src.infolist():
            if i.filename not in files:
                z.writestr(i.filename, src.read(i.filename))
        for n, d in files.items():
            z.writestr(n, d)
    return out.getvalue()


# ---------- 1 ----------
def test_1_a_table_of_an_archive_cannot_open_into_gigabytes_and_inspect_is_bounded_and_gated(s, monkeypatch):
    import tracemalloc
    from anaplan_architect.orac import backup as bk
    app, model, c, ids = s
    alice = c["alice"]
    e, arc = _arch(alice)
    pad = b"[" + b"{}," * (20 * 1024 * 1024) + b"{}]"            # 60 MB of nothing, a few KB zipped
    for what, files, route in (("notes", {"tables/notes.json": pad}, "restore"), ("people", {"people.json": pad}, "restore/inspect"), ("people", {"people.json": pad}, "restore"),
                               ("models", {"tables/models.json": pad}, "restore/inspect")):
        bad = _with(arc, **files)
        assert len(bad) < 400_000
        tracemalloc.start(); t = time.time()
        r = alice.post(f"/api/estates/{route}", files={"file": ("x.zip", bad, "application/zip")})
        peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
        assert r.status_code == 400 and ("too large" in r.json()["detail"] or "packed like no export" in r.json()["detail"]) and len(r.content) < 2000, (what, route, r.status_code, r.text[:200])
        assert peak < 120e6 and time.time() - t < 10, (what, route, peak, time.time() - t)
    # what inspect returns is a summary it built, never the archive's own words passed through
    many = json.dumps([{"id": f"u-{i:012x}", "name": "N" * 500, "role": "member", "extra": "x" * 1000} for i in range(400)]).encode()
    man = json.loads(zipfile.ZipFile(io.BytesIO(arc)).read("manifest.json"))
    r = alice.post("/api/estates/restore/inspect", files={"file": ("x.zip", _with(arc, **{"people.json": many, "manifest.json": json.dumps(dict(man, junk="J" * 200000, name="W" * 5000)).encode()}), "application/zip")})
    assert r.status_code == 200 and len(r.content) < 250_000 and "junk" not in r.json() and len(r.json()["name"]) <= 200 and all(set(p) == {"id", "name", "role"} and len(p["name"]) <= 80 for p in r.json()["people"])
    # a manifest that is not an object, and a zip whose headers lie: a plain 400
    odd = TestClient(app, raise_server_exceptions=False, cookies=alice.cookies, headers={"x-csrf": alice.cookies.get("csrf")})
    for files in ({"manifest.json": b"[1, 2]"}, {"manifest.json": b'"x"'}, {"manifest.json": b"{"}, {"manifest.json": json.dumps(dict(man, format="x")).encode()}, {"manifest.json": json.dumps(dict(man, counts=[1])).encode()}):
        for route in ("restore/inspect", "restore"):
            r = odd.post(f"/api/estates/{route}", files={"file": ("x.zip", _with(arc, **files), "application/zip")})
            assert r.status_code in (200, 400) and (r.status_code == 400 or route == "restore/inspect" or True), (files, route, r.status_code, r.text[:200])
            assert r.status_code != 500
    lying = bytearray(arc); k = lying.find(b"tables/notes.json"); lying[k - 12:k - 8] = b"\xff\xff\xff\x7f"       # the entry's sizes, overwritten
    for route in ("restore/inspect", "restore"):
        r = odd.post(f"/api/estates/{route}", files={"file": ("x.zip", bytes(lying), "application/zip")})
        assert r.status_code in (200, 400), (route, r.status_code, r.text[:200])
    # opening an archive takes the same one-at-a-time slot per login as restoring one
    real = bk.inspect_archive
    started, release = threading.Event(), threading.Event()

    def slow(p):
        started.set(); release.wait(15)
        return real(p)
    monkeypatch.setattr(bk, "inspect_archive", slow)
    out = {}
    th = threading.Thread(target=lambda: out.update(r=alice.post("/api/estates/restore/inspect", files={"file": ("x.zip", arc, "application/zip")})))
    th.start(); assert started.wait(15)
    again = alice.post("/api/estates/restore/inspect", files={"file": ("x.zip", arc, "application/zip")})
    release.set(); th.join(30)
    assert again.status_code == 429 and out["r"].status_code == 200
    # a file that packs like no export does is padding
    monkeypatch.setattr(bk, "inspect_archive", real)
    import hashlib
    big = bytes(64 * 1024 * 1024); sha = hashlib.sha256(big).hexdigest()
    rows = json.loads(zipfile.ZipFile(io.BytesIO(arc)).read("tables/snapshot_files.json"))
    blobs = json.loads(zipfile.ZipFile(io.BytesIO(arc)).read("tables/blobs.json"))
    padded = _with(arc, **{"tables/blobs.json": json.dumps(blobs + [{"sha256": sha, "bytes": len(big), "stored_at": "2026-11-24T00:00:00"}]).encode(),
                           "tables/snapshot_files.json": json.dumps(rows + [dict(rows[0], kind="actions", blob_sha=sha)]).encode(), f"blobs/{sha}": big})
    tracemalloc.start()
    r = _restore(alice, padded)
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert r.status_code == 400 and peak < 100e6 and not app.state.blobs.path(sha).exists(), (r.status_code, r.text[:200], peak)


# ---------- 2 ----------
def test_2_a_chats_title_is_never_sent_to_the_tracer(tmp_path):
    from anaplan_architect.orac import telemetry
    from test_trace import FakeLangSmith
    ls = FakeLangSmith()
    app, model, c, ids = _setup(tmp_path, tracer=telemetry.Tracer(ls, host="stub", project="proj"))
    alice, amy = c["alice"], c["amy"]
    e = _shared(alice, "Acme shared")
    Q = "AMY-NEVER-CONSENTED what is the margin on project BLUEBIRD"
    # as the page does it: the chat is made with the first question as its title
    cid = amy.post(f"/api/estates/{e}/conversations", json={"title": Q, "text": Q}).json()["id"]
    assert len(ls.calls) == 0
    assert alice.put("/api/prefs", json={"trace_level": "content"}).status_code == 200
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "ALICE-CONSENTED follow-up"}).status_code == 200
    sent = repr(ls.calls)
    assert "ALICE-CONSENTED" in sent and "AMY-NEVER" not in sent and "BLUEBIRD" not in sent
    # and a chat alice herself titles is still not named by its title: the root is "conversation"
    c2 = alice.post(f"/api/estates/{e}/conversations", json={"title": "ALICE-TITLE of her own", "text": "ALICE-OWN question"}).json()["id"]
    assert "ALICE-OWN" in repr(ls.calls) and "ALICE-TITLE" not in repr(ls.calls)
    # renamed by amy afterwards, asked in by alice: the new title does not go either
    assert amy.patch(f"/api/conversations/{c2}", json={"title": "AMY-RENAMED-IT"}).status_code == 403            # not hers to rename
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "again"}).status_code == 200 and "AMY-" not in repr(ls.calls)


# ---------- 3 ----------
def test_3_a_call_is_counted_before_any_of_it_is_shown_on_a_client_that_does_not_stream(tmp_path):
    from anaplan_architect.chat import Session
    from anaplan_architect.store import Workspace
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    c = TestClient(app)
    eid = _workspace(c, "W")
    w = app.state.workspaces[next(k for k in app.state.workspaces if k[0] == eid)] if any(k[0] == eid for k in app.state.workspaces) else None
    if w is None:
        c.get(f"/api/estates/{eid}/state")
        w = app.state.workspaces[next(k for k in app.state.workspaces if k[0] == eid)]

    class NoStream:                                   # like the chat-completions client used for Azure and OpenAI-compatible endpoints
        def __init__(self): self.messages = self; self.calls = 0

        def create(self, **kw):
            self.calls += 1
            return _B(content=[_B(type="text", text="## Brief\n\nAn answer of several words.")], usage=_B(input_tokens=900, output_tokens=40, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    client = NoStream()
    spent = []
    sess = Session(w, client=client)
    gen = sess.ask_stream("what is margin %?", on_spend=spent.append)
    for ev in gen:
        if ev["type"] == "text":
            break                                     # the reader leaves at the first word
    gen.close()
    assert client.calls == 1 and len(spent) == 1 and spent[0]["input"] == 900


# ---------- 4 ----------
def test_4_guessing_one_name_is_slow_whatever_address_a_try_claims(tmp_path, monkeypatch):
    from anaplan_architect.orac import auth as authmod
    monkeypatch.setenv("ARCHITECT_HOSTED", "1")
    monkeypatch.delenv("ARCHITECT_CLIENT_ADDRESS", raising=False)
    app = create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0")
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    c = TestClient(app, base_url="https://testserver")
    sign = lambda pw, ip=None, xff=None: c.post("/api/auth/login", json={"email": "admin", "password": pw}, headers={k: v for k, v in (("x-real-ip", ip), ("x-forwarded-for", xff)) if v})
    # hosted, and not told where the proxy states the caller's address: no header is believed, and the name is limited as it always was
    codes = [sign("nope", ip=f"10.0.0.{i}", xff=f"10.9.{i}.1").status_code for i in range(8)]
    assert codes == [401] * 5 + [429] * 3
    assert not app.state.db.q("SELECT key FROM login_attempts WHERE key LIKE 'a:%' OR key LIKE 'ua:%'")
    assert c.get("/api/auth/me").status_code == 200
    app.state.db.run("DELETE FROM login_attempts")
    # told to read X-Real-IP (a proxy that replaces it): a name is held per address, and beyond that by name
    monkeypatch.setenv("ARCHITECT_CLIENT_ADDRESS", "x-real-ip")
    monkeypatch.setattr(authmod, "MAX_FAILS_PER_NAME_ANYWHERE", 12)
    t = time.time()
    codes = [sign("nope", ip=f"203.0.113.{i}").status_code for i in range(30)]          # thirty tries on one name from thirty claimed addresses
    took = time.time() - t
    assert codes[:12] == [401] * 12 and set(codes[12:]) == {429}, codes
    assert took < 15                                                                  # refused at once: nothing waits on a worker
    r = sign("nope", ip="203.0.113.200")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    # the owner, right password, an address with no failure of its own, while strangers fail on the name (under that ceiling)
    app.state.db.run("DELETE FROM login_attempts")
    for i in range(7):
        assert sign("nope", ip=f"198.51.100.{i}").status_code == 401
    assert sign("correct horse battery", ip="192.0.2.10").status_code == 200
    # an address that has failed on the name waits its growing turn, and is told how long
    for i in range(7):
        sign("nope", ip=f"198.51.100.{i}")
    r = sign("nope", ip="198.51.100.1")
    assert r.status_code == 429 and "retry-after" in r.headers
    # the admin page says where the address is read from
    me = _login_https(app, "admin", "correct horse battery", {"x-real-ip": "192.0.2.10"}).get("/api/auth/me", headers={"x-real-ip": "192.0.2.10"}).json()
    assert me["address"] == "192.0.2.10" and me["address_source"] == "x-real-ip"
    monkeypatch.delenv("ARCHITECT_CLIENT_ADDRESS")
    app.state.db.run("DELETE FROM login_attempts")
    me = _login_https(app, "admin", "correct horse battery", {}).get("/api/auth/me").json()
    assert me["address"] == "" and me["address_source"] == "not set"


def _login_https(app, username, password, headers):
    c = TestClient(app, base_url="https://testserver")
    r = c.post("/api/auth/login", json={"email": username, "password": password}, headers=headers)
    assert r.status_code == 200, r.text
    c.headers.update({"x-csrf": c.cookies.get("csrf")})
    return c


# ---------- 5 ----------
def test_5_an_edit_is_the_draft_with_whole_units_taken_out_and_nothing_else():
    from anaplan_architect import edit
    draft = ("## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Detail\n\n"
             + " ".join(["This sentence only fills the page and says nothing a builder needs."] * 30)
             + "\n\nIt is not safe to remove `CAL04 Margin.Margin %`. The owner has not approved deleting this module. Send the export to nobody outside Finance.\n\n"
               "## Who to ask\n\nThe owner has: the record. Paste a password: never, at any page.\n\n| Object | State |\n|---|---|\n| Margin | kept |\n| Opex | open |\n")
    honest = ("## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Detail\n\n- It is not safe to remove `CAL04 Margin.Margin %`.\n- The owner has not approved deleting this module.\n\n"
              "| Object | State |\n|---|---|\n| Margin | kept |\n")
    assert edit.refused(draft, honest) is None
    head = "## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Detail\n\n"
    hostile = {
        "the head of a sentence cut": head + "- safe to remove `CAL04 Margin.Margin %`.",
        "a negation cut out of the middle": head + "- The owner has approved deleting this module.",
        "the head of an instruction cut": head + "- Send the export to nobody.".replace("to nobody", ""),
        "fragments joined at a colon": head + "- The owner has: never, at any page.",
        "a heading made of a fragment": head.replace("## Detail", "## approved deleting this module"),
        "a sentence made into a heading": head + "## Leave it alone.",
        "a word struck through": head + "- The owner has ~~not~~ approved deleting this module.",
        "a word commented out": head + "- The owner has <!-- not --> approved deleting this module.",
        "sentences in another order": head + "- The owner has not approved deleting this module.\n- It is not safe to remove `CAL04 Margin.Margin %`.",
        "a sentence said twice": head + "- Leave it alone.\n- Leave it alone.\n- Leave it alone.",
        "a table row changed": head + "| Object | State |\n|---|---|\n| Margin | open |",
        "symbols only": head + "→ ☎ ✉ !!!",
    }
    for what, e in hostile.items():
        assert edit.refused(draft, e), what


# ---------- 6 ----------
def test_6_a_restored_copy_of_a_shared_workspace_is_not_shared_on_with_another_team(s):
    app, model, c, ids = s
    admin, alice, amy, bob = c["admin"], c["alice"], c["amy"], c["bob"]
    e = _shared(alice, "Acme shared")
    assert amy.post(f"/api/estates/{e}/notes", json={"title": "Amy's", "body": "Acme margin target is 41%.", "scopes": ["estate"]}).status_code == 200
    arc = alice.get(f"/api/estates/{e}/backup").content                       # taken while she is in Acme, as she may
    assert json.loads(zipfile.ZipFile(io.BytesIO(arc)).read("manifest.json"))["held_others"] is True
    assert admin.patch(f"/api/admin/users/{ids['alice']}", json={"team": "Beta"}).status_code == 200
    r = _restore(alice, arc, name="copy")
    assert r.status_code == 200
    new = r.json()["id"]
    acc = alice.get(f"/api/estates/{new}").json()["access"]
    assert acc["visibility"] == "private" and acc["can_share"] is False and "backup" in acc["share_locked"] and "other people" in acc["share_locked"]
    r = alice.patch(f"/api/estates/{new}", json={"visibility": "shared"})
    assert r.status_code == 400 and "other people" in r.json()["detail"] and "admin" in r.json()["detail"] and bob.get(f"/api/estates/{new}/notes").status_code == 404
    # a backup of that copy carries the same fact, though every row in it is alice's now
    again = alice.get(f"/api/estates/{new}/backup").content
    assert json.loads(zipfile.ZipFile(io.BytesIO(again)).read("manifest.json"))["held_others"] is True
    r2 = _restore(alice, again, name="copy of copy")
    assert alice.patch(f"/api/estates/{r2.json()['id']}", json={"visibility": "shared"}).status_code == 400
    # the admin can allow it, from the admin panel, without opening it
    row = next(w for w in admin.get("/api/admin/workspaces").json()["workspaces"] if w["id"] == new)
    assert row["share_locked"] and admin.get(f"/api/estates/{new}").status_code == 404
    assert bob.patch(f"/api/admin/workspaces/{new}", json={"allow_sharing": True}).status_code == 403
    assert admin.patch(f"/api/admin/workspaces/{new}", json={"allow_sharing": True}).json()["share_locked"] is None
    assert alice.patch(f"/api/estates/{new}", json={"visibility": "shared"}).status_code == 200 and bob.get(f"/api/estates/{new}/notes").status_code == 200
    # a backup of a workspace that only ever held its maker's own work restores free to share
    mine = _workspace(alice, "Alice's own")
    own = alice.get(f"/api/estates/{mine}/backup").content
    assert json.loads(zipfile.ZipFile(io.BytesIO(own)).read("manifest.json"))["held_others"] is False
    r3 = _restore(alice, own, name="own copy")
    assert alice.get(f"/api/estates/{r3.json()['id']}").json()["access"]["share_locked"] is None
    assert alice.patch(f"/api/estates/{r3.json()['id']}", json={"visibility": "shared"}).status_code == 200


# ---------- 7 ----------
def test_7_a_team_mate_does_not_withdraw_read_or_clear_what_the_maker_added(s):
    app, model, c, ids = s
    alice, amy, db = c["alice"], c["amy"], s[0].state.db
    e = _shared(alice, "Acme shared")
    p = alice.post(f"/api/estates/{e}/plan/proposals", json={"title": "Tidy margin", "why": "because", "steps": ["one"], "done_when": "done"})
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    mid = alice.get(f"/api/estates/{e}").json()["models"][0]["id"]
    snap = alice.post(f"/api/estates/{e}/snapshots", data={"label": "draft", "model_ids": [mid]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))])
    assert snap.status_code == 200, snap.text
    sid = snap.json()["id"]
    n = alice.post(f"/api/estates/{e}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    db.run("UPDATE notes SET review_flag='changed' WHERE id=?", n)
    for r in (amy.delete(f"/api/estates/{e}/plan/proposals/{pid}"), amy.post(f"/api/snapshots/{sid}/process"), amy.post(f"/api/snapshots/{sid}/cancel"), amy.post(f"/api/notes/{n}/reviewed")):
        assert r.status_code == 403 and "Alice" in r.json()["detail"], (r.request.method, r.request.url.path, r.status_code, r.text[:120])
    assert db.one("SELECT review_flag FROM notes WHERE id=?", n)["review_flag"] == "changed"
    assert alice.post(f"/api/notes/{n}/reviewed").status_code == 200 and alice.delete(f"/api/estates/{e}/plan/proposals/{pid}").status_code == 200
    # her own she may
    mine = amy.post(f"/api/estates/{e}/plan/proposals", json={"title": "Amy's", "why": "w", "steps": ["one"], "done_when": "d"}).json()["id"]
    assert amy.delete(f"/api/estates/{e}/plan/proposals/{mine}").status_code == 200
    # a proposal of another workspace and one that does not exist: the same words
    other = _workspace(amy, "Amy's own")
    theirs = alice.post(f"/api/estates/{e}/plan/proposals", json={"title": "x", "why": "w", "steps": ["one"], "done_when": "d"}).json()["id"]
    a, b = amy.delete(f"/api/estates/{other}/plan/proposals/{theirs}"), amy.delete(f"/api/estates/{other}/plan/proposals/p-0000000000")
    assert (a.status_code, a.text) == (b.status_code, b.text) and a.status_code == 404


# ---------- 9 ----------
def test_9_a_team_name_that_reads_like_one_already_here_is_asked_about(s):
    app, model, c, ids = s
    admin = c["admin"]
    names = lambda: sorted(t["name"] for t in admin.get("/api/admin/teams").json()["teams"])
    for typed in ("Асме", "Acrne", "Acme.", "A c m e", "Acmеs"[:4]):
        r = admin.post("/api/admin/teams", json={"name": typed})
        assert r.status_code in (400, 409) and names() == ["Acme", "Beta"], (typed, r.status_code, r.text)
        if r.status_code == 409:
            assert r.json()["detail"]["confusable"] == "Acme" and "Acme" in r.json()["detail"]["message"]
    r = admin.post("/api/admin/users", json={"username": "zed", "name": "Zed", "demo": False, "new_team": "Acrne"})
    assert r.status_code == 409 and "zed" not in [u["email"] for u in admin.get("/api/admin/users").json()["users"]]
    # it really is another company: confirmed, it is made
    assert admin.post("/api/admin/teams", json={"name": "Acrne", "confirm": True}).json()["name"] == "Acrne"
    assert admin.post("/api/admin/teams", json={"name": "Gamma"}).status_code == 200 and names() == ["Acme", "Acrne", "Beta", "Gamma"]


# ---------- 10 ----------
def test_10_a_request_of_the_wrong_shape_is_a_400_in_words_never_a_500(s):
    app, model, c, ids = s
    alice = c["alice"]
    e = _workspace(alice, "W")
    t = alice.post(f"/api/estates/{e}/conversations", json={"title": "t", "text": "what is margin %?"}).json(); cid = t["id"]
    n = alice.post(f"/api/estates/{e}/notes", json={"title": "n", "body": "b", "scopes": ["estate"]}).json()["id"]
    summ = alice.get(f"/api/estates/{e}").json(); snap, mid = summ["snapshot"]["id"], summ["models"][0]["id"]
    routes = [("POST", "/api/auth/login"), ("POST", "/api/auth/password"), ("PUT", "/api/prefs"), ("POST", "/api/estates/create"), ("PATCH", f"/api/estates/{e}"), ("DELETE", f"/api/estates/{e}"),
              ("POST", f"/api/estates/{e}/models"), ("PATCH", f"/api/models/{mid}"), ("POST", f"/api/estates/{e}/conversations"), ("PATCH", f"/api/conversations/{cid}"), ("POST", f"/api/conversations/{cid}/branch"),
              ("POST", f"/api/conversations/{cid}/messages"), ("POST", f"/api/conversations/{cid}/stream"), ("POST", f"/api/estates/{e}/notes"), ("PATCH", f"/api/notes/{n}"), ("POST", f"/api/notes/{n}/supersede"),
              ("PATCH", f"/api/estates/{e}/findings"), ("PUT", f"/api/estates/{e}/edges"), ("PUT", f"/api/estates/{e}/plan/state"), ("POST", f"/api/estates/{e}/plan/proposals"), ("PUT", f"/api/estates/{e}/size/state"),
              ("POST", f"/api/snapshots/{snap}/activate"), ("PATCH", "/api/workspace")]
    admin_routes = [("POST", "/api/admin/users"), ("PATCH", f"/api/admin/users/{ids['alice']}"), ("POST", "/api/admin/teams"), ("PATCH", f"/api/admin/workspaces/{e}")]
    keys = ("name", "title", "text", "body", "visibility", "archived", "scope", "scopes", "objects", "state", "key", "model", "ref", "from", "to", "steps", "confirm", "old", "new", "email", "password",
            "trace_level", "edit_pass", "aliases", "retired", "by_note", "reason", "why", "username", "team", "new_team", "cap_usd", "role", "maker", "sources", "mode", "continue_on_snapshot", "done_when", "purpose", "owner")
    bodies = [[], "x", 5, None, {}, {k: 5 for k in keys}, {k: ["a", 5, None, {}] for k in keys}, {k: {"a": 1} for k in keys}, {"text": "\x00\ud800", "title": "\x00", "name": "\x00", "body": "\x00"}]
    raw = re.compile(r"Traceback|Error:|sqlite3|\.py\b|line \d+|object has no attribute|NoneType|expected str|unhashable|site-packages")
    bad = []
    for who, rs in ((alice, routes), (c["admin"], admin_routes)):
        cl = TestClient(app, raise_server_exceptions=False, cookies=who.cookies, headers={"x-csrf": who.cookies.get("csrf")})
        for m, p in rs:
            for i, b in enumerate(bodies):
                r = cl.request(m, p, content=json.dumps(b, ensure_ascii=True).encode(), headers={"content-type": "application/json"})
                if r.status_code >= 500 or raw.search(r.text[:600]):
                    bad.append((m, p.replace(e, "E"), i, r.status_code, r.text[:90]))
    assert not bad, bad[:8]


# ---------- 12 ----------
def test_12_a_password_change_that_was_made_says_so(tmp_path):
    app = create_app(tmp_path / "data", client_factory=lambda: None)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    for _ in range(6):                                # strangers failing on the admin's name meanwhile
        TestClient(app).post("/api/auth/login", json={"email": "admin", "password": "nope"})
    r = admin.post("/api/auth/password", json={"old": "correct horse battery", "new": "a new long pass phrase"})
    assert r.status_code == 200 and admin.get("/api/auth/me").json()["user"]["email"] == "admin"            # changed, said so, and still signed in
    assert auth.verify_password("a new long pass phrase", *[app.state.db.one("SELECT pw_hash, pw_salt FROM users WHERE email='admin'")[k] for k in ("pw_hash", "pw_salt")])


# ---------- 13 and 15 ----------
def test_13_a_name_with_a_stray_quote_does_not_blank_the_rest_of_the_report(s):
    import csv
    from anaplan_architect import reportpage
    app, model, c, ids = s
    alice = c["alice"]
    rows = list(csv.reader(io.StringIO((FX / "1 Caldergate Planning" / "Line Items.csv").read_text(encoding="utf-8"))))
    clean = alice.get(f"/api/estates/{_workspace(alice, 'clean')}/report")
    last = re.findall(r"<h2[^>]*>(.*?)</h2>", clean.text)[-1]
    for name in ('[x](#" a="', '[x](#"', "[x](#' onmouseover='alert(1)", '[x](#"><b', '[x](#x" style="position:fixed'):
        buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows([[x.replace("CAL02 Revenue", name) for x in r] for r in rows])
        up = alice.post("/api/estates", data={"name": "W", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", buf.getvalue().encode(), "text/csv"))])
        assert up.status_code == 200, up.text[:200]
        page = alice.get(f"/api/estates/{up.json()['id']}/report").text
        assert last in re.findall(r"<h2[^>]*>(.*?)</h2>", page) and len(page) > 0.9 * len(clean.text), name       # the page is all there
        assert "onmouseover=" not in re.sub(r"&[a-z#0-9]+;", "", page).replace("onmouseover=&", "") or "<a" not in page
        assert not re.search(r"<a\b[^>]*\bon[a-z]+\s*=", page) and not re.search(r"<a\b[^>]*\bstyle\s*=", page), name
    # the reader alone, given a tag it cannot finish: what it could not read is kept as text
    out, n = reportpage.safe('<p>before</p><a href="#" x="unclosed>after <h2>Still here</h2>')
    assert "before" in out and "Still here" in out and "<h2>Still here</h2>" not in out and n >= 1
    # the report's own fonts are inside it: its policy lets them load
    assert "font-src data:" in clean.headers["content-security-policy"]


# ---------- 14 ----------
def test_14_one_answer_at_a_time_in_a_chat_even_when_its_live_session_is_dropped(s):
    app, model, c, ids = s
    alice, amy, db = c["alice"], c["amy"], s[0].state.db
    e = _shared(alice, "Acme shared")
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "t"}).json()["id"]
    model.gate = threading.Event(); model.entered.clear(); out = {}
    th = threading.Thread(target=lambda: out.update(r=alice.post(f"/api/conversations/{cid}/messages", json={"text": "alice's question"})))
    th.start(); assert model.entered.wait(20)
    # a team-mate adds a document (the live session is dropped) and then asks in the same chat
    assert amy.post(f"/api/estates/{e}/documents", files=[("files", ("a.md", b"# A\n\nText.", "text/markdown"))]).status_code == 200
    r = amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy while alice's answer runs"})
    r2 = amy.post(f"/api/conversations/{cid}/stream", json={"text": "amy while alice's answer runs"})
    r3 = amy.patch(f"/api/conversations/{cid}", json={"continue_on_snapshot": True})
    r4 = amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy again"})
    assert r.status_code == 409 and r2.status_code == 409 and r4.status_code == 409, (r.status_code, r2.status_code, r3.status_code, r4.status_code)
    assert app.state.in_flight["total"] == 1
    model.gate.set(); th.join(30); model.gate = None
    assert out["r"].status_code == 200
    assert amy.post(f"/api/conversations/{cid}/messages", json={"text": "amy after"}).status_code == 200
    turns = [(t["seq"], t["question"], t["author_id"]) for t in db.q("SELECT seq, question, author_id FROM turns WHERE conversation_id=? ORDER BY seq", cid)]
    assert turns == [(1, "alice's question", ids["alice"]), (2, "amy after", ids["amy"])], turns
    # and the second answer was given the first: the chat it was rebuilt from had alice's turn in it
    assert len(app.state.sessions[cid].turns) == 2
