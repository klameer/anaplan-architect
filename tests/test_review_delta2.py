"""Security review of everything since 13 November except sharing (2026-11-24, at bf13414), continued: H2, M1 to M4
and the low findings. One test per finding, written to fail first. H1 is in test_review_delta.py."""
import sys, pathlib, json, io, zipfile, threading, csv, time
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from anaplan_architect.orac import auth
from test_access import _login, _workspace, _no_real_backend, _B, FX      # noqa: F401
from test_review_sharing import _setup, _restore


@pytest.fixture()
def s(tmp_path):
    return _setup(tmp_path)


# ---------- H2 ----------
def _big_exports(modules=60, items=50):
    hdr = ["", "Format", "Formula", "Summary", "Applies To", "Time Scale", "Time Range", "Versions", "Style", "Cell Count", "Notes", "Referenced By", "Module Name"]
    rows = [hdr]
    for m in range(modules):
        mod = f"CAL{m:04d} Module {m}"
        rows.append([mod, "", "", "", "", "Not Applicable", "Not Applicable", "Not Applicable", "", "0", "", "", ""])
        rows += [[f"Item {i}", '{"dataType":"NUMBER"}', "", "", "", "Month", "Model Calendar", "Not Applicable", "", "24", "", "", mod] for i in range(items)]
    buf = io.StringIO(); csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode()


def test_h2_a_long_document_in_a_large_model_is_linked_fast_and_outside_the_write_lock(s, monkeypatch):
    from anaplan_architect.orac import documents as docsmod
    app, model, c, ids = s
    alice, bob = c["alice"], c["bob"]
    big = alice.post("/api/estates", data={"name": "Big", "model_names": ["Big"]}, files=[("line_items", ("Line Items.csv", _big_exports(), "text/csv"))]).json()["id"]
    small = _workspace(bob, "Small")
    para = ("The quarterly review covered many things and none of them is a module of this model. " * 8).strip()
    doc = ("# Minutes\n\nCAL0003 Module 3 was discussed, and 'CAL0007 Module 7'.Item 12 too.\n\n" + "\n\n".join(para for _ in range(700))).encode()      # about half a megabyte
    # 3,060 objects, hundreds of sections: seconds, not minutes
    t = time.time()
    r = alice.post(f"/api/estates/{big}/documents", files=[("files", ("minutes.md", doc, "text/markdown"))])
    took = time.time() - t
    assert r.status_code == 200 and r.json()["results"][0]["ok"], r.text[:300]
    assert took < 20, f"{took:.0f}s"
    named = {(o["kind"], o["ref"]) for o in r.json()["results"][0]["document"]["objects"]}
    assert named == {("module", "CAL0003 Module 3"), ("line_item", "CAL0007 Module 7.Item 12"), ("module", "CAL0007 Module 7")}, named
    # and while the linking runs, however long it takes, nobody else's write waits: it is not inside the transaction
    real = docsmod.Linker.links
    started, release = threading.Event(), threading.Event()

    def slow(self, text):
        started.set(); release.wait(15)
        return real(self, text)
    monkeypatch.setattr(docsmod.Linker, "links", slow)
    out = {}
    th = threading.Thread(target=lambda: out.update(r=alice.post(f"/api/estates/{big}/documents", files=[("files", ("second.md", b"# Second\n\nCAL0001 Module 1.", "text/markdown"))])))
    th.start()
    assert started.wait(15)
    t = time.time()
    w1 = bob.post(f"/api/estates/{small}/notes", json={"title": "n", "body": "written while alice's document is being read", "scopes": ["estate"]})
    w2 = TestClient(app).post("/api/auth/login", json={"email": "bob", "password": "not it"})
    waited = time.time() - t
    release.set(); th.join(30)
    assert w1.status_code == 200 and w2.status_code == 401 and waited < 3, (w1.status_code, w2.status_code, waited)
    assert out["r"].status_code == 200 and out["r"].json()["results"][0]["ok"]


def test_h2_a_model_call_is_never_counted_as_free(s, monkeypatch):
    import sqlite3
    app, model, c, ids = s
    alice, db = c["alice"], s[0].state.db
    e = _workspace(alice, "Acme")
    cid = alice.post(f"/api/estates/{e}/conversations", json={"title": "t"}).json()["id"]
    real = auth.record_spend
    fails = {"n": 2}

    def flaky(*a, **kw):
        if fails["n"] > 0:
            fails["n"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **kw)
    monkeypatch.setattr(auth, "record_spend", flaky)
    rows = lambda: db.one("SELECT COUNT(*) AS n FROM spend WHERE user_id=?", ids["alice"])["n"]
    # busy for a moment: tried again, and both calls of the answer are on the ledger
    assert alice.post(f"/api/conversations/{cid}/messages", json={"text": "what is margin %?"}).status_code == 200 and rows() == 2
    # busy for good: the turn stops with a plain message, and nothing is shown or kept
    fails["n"] = 10 ** 6
    turns = lambda: db.one("SELECT COUNT(*) AS n FROM turns WHERE conversation_id=?", cid)["n"]
    calls = model.calls
    r = alice.post(f"/api/conversations/{cid}/messages", json={"text": "and again?"})
    assert r.status_code == 503 and "could not be recorded" in r.json()["detail"] and "never counted as free" in r.json()["detail"]
    assert turns() == 1 and model.calls == calls + 1                    # stopped after the one call that could not be counted
    r = alice.post(f"/api/conversations/{cid}/stream", json={"text": "and again?"})
    assert r.status_code == 200 and "could not be recorded" in r.text and "CAL04" not in r.text and turns() == 1
    # a store that is busy when someone signs in is a 503 in words, never a bare 500
    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(auth, "login", locked)
    r = TestClient(app, raise_server_exceptions=False).post("/api/auth/login", json={"email": "alice", "password": "x"})
    assert r.status_code == 503 and "busy" in r.json()["detail"] and "retry-after" in r.headers


def test_h2_uploads_are_gated_one_of_each_kind_per_login(s, monkeypatch):
    from anaplan_architect.orac import documents as docsmod
    app, model, c, ids = s
    alice, bob = c["alice"], c["bob"]
    ea, eb = _workspace(alice, "A"), _workspace(bob, "B")
    real = docsmod.add
    started, release = threading.Event(), threading.Event()

    def slow(*a, **kw):
        started.set(); release.wait(15)
        return real(*a, **kw)
    monkeypatch.setattr(docsmod, "add", slow)
    doc = [("files", ("a.md", b"# A\n\nText.", "text/markdown"))]
    out = {}
    th = threading.Thread(target=lambda: out.update(r=alice.post(f"/api/estates/{ea}/documents", files=doc)))
    th.start()
    assert started.wait(15)
    again = alice.post(f"/api/estates/{ea}/documents", files=doc)                   # the same login, a second batch while the first is read
    assert again.status_code == 429 and "already" in again.json()["detail"] and "retry-after" in again.headers
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    other = alice.post("/api/estates", data={"name": "A2", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))])
    assert other.status_code == 200                                                    # a different kind of work is not held up by it
    release.set(); th.join(30)
    assert out["r"].status_code == 200 and bob.post(f"/api/estates/{eb}/documents", files=doc).status_code == 200
    assert alice.post(f"/api/estates/{ea}/documents", files=doc).status_code == 200  # and the slot came back
    # a login's export files have a ceiling
    app.state.limits["storage_mb_per_login"] = 0
    r = alice.post("/api/estates", data={"name": "A3", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))])
    assert r.status_code == 413 and "limit" in r.json()["detail"]


# ---------- M1 ----------
class _Stream:
    def __init__(self, o): self.o = o
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def __iter__(self):
        for i in range(60):
            time.sleep(0.05); self.o.deltas += 1
            yield _B(type="content_block_delta", delta=_B(type="text_delta", text=f"word{i} "))

    def get_final_message(self):
        self.o.finals += 1
        return _B(content=[_B(type="text", text="## Brief\n\n" + "word " * 40)], usage=_B(input_tokens=30000, output_tokens=2000, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Streaming:
    def __init__(self): self.messages = self; self.calls = 0; self.deltas = 0; self.finals = 0
    def stream(self, **kw): self.calls += 1; return _Stream(self)


def test_m1_a_dropped_stream_is_paid_for_and_gives_its_lock_and_slot_back_at_once(tmp_path):
    import gc, socket, http.client, uvicorn
    model = _Streaming()
    app = create_app(tmp_path / "data", client_factory=lambda: model)
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    admin = _login(app, "admin", "correct horse battery")
    pw = admin.post("/api/admin/users", json={"username": "mal", "name": "Mal", "demo": False}).json()["password"]
    m = _login(app, "mal", pw)
    uid = app.state.db.one("SELECT id FROM users WHERE email='mal'")["id"]
    eid = _workspace(m, "M")
    cids = [m.post(f"/api/estates/{eid}/conversations", json={"title": f"t{i}"}).json()["id"] for i in range(3)]
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    while not server.started:
        time.sleep(0.05)
    hdr = {"cookie": "; ".join(f"{k}={v}" for k, v in m.cookies.items()), "x-csrf": m.cookies.get("csrf"), "content-type": "application/json"}

    def ask(cid, read_events):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("POST", f"/api/conversations/{cid}/stream", body=json.dumps({"text": "say a lot"}), headers=hdr)
        r = conn.getresponse(); got = 0
        if r.status != 200:
            out = (r.status, r.read()[:200]); conn.close(); return out
        while True:
            line = r.fp.readline()
            if not line:
                break
            if line.startswith(b"data: "):
                got += 1
                if read_events and got >= read_events:
                    break
        conn.close()
        return r.status, got
    spend = lambda: app.state.db.one("SELECT COUNT(*) AS n, COALESCE(SUM(usd),0) AS usd FROM spend WHERE user_id=?", uid)
    gc.disable()                                     # so that nothing here is owed to a collection happening to run
    try:
        assert ask(cids[0], 8)[0] == 200 and ask(cids[1], 8)[0] == 200          # two streams, each dropped after a few events
        deadline = time.time() + 8
        while time.time() < deadline and (app.state.in_flight["total"] or any(app.state.sessions[x].lock.locked() for x in cids[:2])):
            time.sleep(0.1)
        assert app.state.in_flight == {"total": 0, "by_login": {}}, app.state.in_flight
        assert not any(app.state.sessions[x].lock.locked() for x in cids[:2])
        # what the dropped calls cost is on the ledger: the request that was sent, and what had been written
        sp = spend()
        assert sp["n"] == 2 and sp["usd"] > 0, sp
        assert model.finals == 0                                                  # the provider never gave a usage figure for them: it is an estimate
        # and the login can ask again at once, in the same chat and in a third
        assert ask(cids[0], None)[0] == 200 and ask(cids[2], None)[0] == 200 and spend()["n"] == 4
    finally:
        gc.enable(); server.should_exit = True; th.join(10)


# ---------- M2 ----------
def _login_h(app, username, password, headers):
    c = TestClient(app, base_url="https://testserver")                  # hosted mode sets Secure cookies: they travel over https only
    assert c.post("/api/auth/login", json={"email": username, "password": password}, headers=headers).status_code == 200
    c.headers.update({"x-csrf": c.cookies.get("csrf")})
    return c


def test_m2_a_name_is_not_locked_for_everyone_and_a_made_up_address_is_not_believed(tmp_path, monkeypatch):
    from anaplan_architect.orac import auth as authmod
    monkeypatch.setenv("ARCHITECT_HOSTED", "1"); monkeypatch.setenv("ARCHITECT_CLIENT_ADDRESS", "x-real-ip")
    app = create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0")
    auth.create_owner(app.state.db, app.state.workspace_id, "admin", "Admin", "correct horse battery")
    c = TestClient(app)
    sign = lambda pw, **h: c.post("/api/auth/login", json={"email": "admin", "password": pw}, headers=h)
    # five wrong passwords for the admin's name from one address: that address is held, on that name
    for _ in range(5):
        assert sign("nope", **{"x-real-ip": "203.0.113.9"}).status_code == 401
    assert sign("correct horse battery", **{"x-real-ip": "203.0.113.9"}).status_code == 429
    # the admin, from their own address, with the right password, still gets in
    r = sign("correct horse battery", **{"x-real-ip": "198.51.100.7"})
    assert r.status_code == 200
    # a caller who writes a new address into X-Forwarded-For with every try is counted under the address the proxy saw
    c2 = TestClient(app)
    codes = [c2.post("/api/auth/login", json={"email": f"user{i}", "password": "x"}, headers={"x-forwarded-for": f"10.9.{i}.1, 203.0.113.50", "x-real-ip": "203.0.113.50"}).status_code for i in range(25)]
    assert codes[:20] == [401] * 20 and codes[20:] == [429] * 5
    keys = {r["key"] for r in app.state.db.q("SELECT key FROM login_attempts WHERE key LIKE 'a:%'")}
    assert keys == {"a:203.0.113.9", "a:203.0.113.50"}
    # told to read X-Forwarded-For, the entry counted from the right is used, never the leftmost
    monkeypatch.setenv("ARCHITECT_CLIENT_ADDRESS", "xff:1")
    assert c2.post("/api/auth/login", json={"email": "z", "password": "x"}, headers={"x-forwarded-for": "10.1.1.1, 192.0.2.44"}).status_code == 401
    assert app.state.db.one("SELECT COUNT(*) AS n FROM login_attempts WHERE key='a:192.0.2.44'")["n"] == 1
    monkeypatch.setenv("ARCHITECT_CLIENT_ADDRESS", "x-real-ip")
    # fields that are not text are a 400, not a 500
    for body in ({"email": ["a"], "password": "x"}, {"email": "admin2", "password": 5}, {"email": None, "password": None}, ["x"]):
        r = TestClient(app, raise_server_exceptions=False).post("/api/auth/login", json=body, headers={"x-real-ip": "192.0.2.99"})
        assert r.status_code in (400, 401, 422), (body, r.status_code)
    # changing a password is not a way to guess the current one without limit
    admin = _login_h(app, "admin", "correct horse battery", {"x-real-ip": "198.51.100.7"})
    codes = [admin.post("/api/auth/password", json={"old": f"guess {i}", "new": "a new long pass phrase"}, headers={"x-real-ip": "198.51.100.7"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429] * 2


# ---------- M3 ----------
def test_m3_a_small_upload_cannot_open_into_gigabytes(s, monkeypatch):
    import hashlib, tracemalloc
    from anaplan_architect.orac import documents as docsmod, snapshots as snapmod
    app, model, c, ids = s
    alice = c["alice"]
    # a Word file of a hundred KB that unzips to the limit: read as it streams, refused by what it holds
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    p = "<w:p><w:r><w:t>a</w:t></w:r></w:p>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>' + p * ((docsmod.MAX_UNZIPPED - 400) // len(p)) + "</w:body></w:document>")
    assert len(buf.getvalue()) < 300_000
    tracemalloc.start()
    secs, problem, ext = docsmod.read_file("x.docx", buf.getvalue())
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert secs == [] and "paragraphs" in problem and peak < 150e6, (problem, peak)
    # an ordinary Word file still reads, headings and all
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Margin</w:t></w:r></w:p>'
                                        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>In a </w:t></w:r><w:r><w:t>table.</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>After.</w:t></w:r></w:p></w:body></w:document>')
    secs, problem, ext = docsmod.read_file("ok.docx", buf.getvalue())
    assert problem is None and secs[0]["heading"] == "Margin" and "In a table." in secs[0]["text"] and "After." in secs[0]["text"]
    # a backup whose one export file opens far past what an upload of exports may be
    monkeypatch.setattr(snapmod, "MAX_MB", 8.0)
    e = _workspace(alice, "Mine")
    arc = alice.get(f"/api/estates/{e}/backup").content
    assert alice.request("DELETE", f"/api/estates/{e}", json={"confirm": "Mine"}).status_code == 200
    files = lambda: {q for q in app.state.blobs.root.rglob("*") if q.is_file()}
    before = files()

    def with_blob(data, used=False):
        sha = hashlib.sha256(data).hexdigest()
        src = zipfile.ZipFile(io.BytesIO(arc)); out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for i in src.infolist():
                d = src.read(i.filename)
                if i.filename == "tables/blobs.json":
                    d = json.dumps(json.loads(d) + [{"sha256": sha, "bytes": len(data), "stored_at": "2026-11-24T00:00:00"}]).encode()
                if i.filename == "tables/snapshot_files.json" and used:
                    rows = json.loads(d); d = json.dumps(rows + [dict(rows[0], kind="actions", blob_sha=sha)]).encode()
                z.writestr(i.filename, d)
            z.writestr(f"blobs/{sha}", data)
        return out.getvalue(), sha
    big, sha = with_blob(bytes(32 * 1024 * 1024), used=True)
    assert len(big) < 200_000
    tracemalloc.start()
    r = _restore(alice, big)
    peak = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
    assert r.status_code == 400 and "too large" in r.json()["detail"] and peak < 20e6, (r.status_code, r.text[:200], peak)
    # one under the limit that nothing in the archive uses is refused too, and neither leaves a file on the volume
    orphan, sha2 = with_blob(bytes(2 * 1024 * 1024))
    r = _restore(alice, orphan)
    assert r.status_code == 400 and "none of its uploads uses" in r.json()["detail"]
    assert files() <= before and not app.state.blobs.path(sha).exists() and not app.state.blobs.path(sha2).exists()
    assert _restore(alice, arc).status_code == 200                                 # the honest archive still restores


# ---------- M4 ----------
def test_m4_the_editing_pass_can_only_cut():
    from anaplan_architect import edit
    draft = ("## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Detail\n\n"
             + " ".join(["This sentence only fills the page and says nothing a builder needs."] * 30) + "\n\nIt is deliberate; Finance asked for it. See https://intranet.example/margin for the record.\n")
    keep = "## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Detail\n\n- It is deliberate; Finance asked for it.\n- See https://intranet.example/margin for the record."
    assert edit.refused(draft, keep) is None
    hostile = {
        "a new section, a claim and a link": "## Brief\n\n`CAL04 Margin.Margin %` is the divide and it is kept. Leave it alone.\n\n## Action required\n\nThe owner has approved deleting this module. "
                                             "Your session has expired: [sign in again to continue](https://evil.example/login) and paste your password there.",
        "one new sentence": keep + "\n- The owner has approved deleting this module.",
        "a sentence turned round": keep.replace("It is deliberate", "It is not deliberate"),
        "a bare address": keep + "\n- More at evil.example/login.",
        "a link to somewhere else": keep.replace("https://intranet.example/margin", "https://intranet.example.evil.example/margin"),
        "a new heading": keep.replace("## Detail", "## Urgent"),
        "two sentences joined into a new one": keep.replace("Leave it alone.", "Leave it alone because Finance asked for it to be deleted."),
    }
    for what, e in hostile.items():
        why = edit.refused(draft, e)
        assert why and ("the draft did not" in why or "link or an address" in why), (what, why)
    assert "word for word" in edit.SYSTEM and "link" in edit.SYSTEM


# ---------- low ----------
def test_low_tracing_is_not_turned_on_for_a_login_by_making_it_an_admin(tmp_path):
    from anaplan_architect.orac import telemetry
    from test_trace import FakeLangSmith
    ls = FakeLangSmith()
    app, model, c, ids = _setup(tmp_path, tracer=telemetry.Tracer(ls, host="stub", project="proj"), people=(("ann", None),))
    admin, ann = c["admin"], c["ann"]
    e = _workspace(ann, "Ann's")
    Q = "what is the margin on project BLUEBIRD"
    ann.post(f"/api/estates/{e}/conversations", json={"title": "t", "text": Q})
    assert len(ls.calls) == 0 and ann.get("/api/auth/me").json()["trace"]["level"] == "off"
    assert admin.patch(f"/api/admin/users/{ids['ann']}", json={"role": "owner"}).status_code == 200          # ann did nothing
    ann.post(f"/api/estates/{e}/conversations", json={"title": "t2", "text": Q})
    tr = ann.get("/api/auth/me").json()["trace"]
    assert "BLUEBIRD" not in repr(ls.calls) and len(ls.calls) == 0 and tr["level"] == "off" and tr["default"] == "off"
    assert admin.get("/api/auth/me").json()["trace"]["default"] == "content"                               # the login the instance was set up with
    assert ann.put("/api/prefs", json={"trace_level": "content"}).status_code == 200                       # her own choice turns it on
    ann.post(f"/api/estates/{e}/conversations", json={"title": "t3", "text": Q})
    assert "BLUEBIRD" in repr(ls.calls)


def test_low_what_a_call_costs_on_a_paid_route_that_is_not_claude(monkeypatch):
    from anaplan_architect import chat
    u = {"input": 1_000_000, "output": 100_000, "cache_read": 500_000, "cache_write": 0}
    for k in ("ARCHITECT_PRICE_IN", "ARCHITECT_PRICE_OUT", "ARCHITECT_PRICE_CACHED"):
        monkeypatch.delenv(k, raising=False)
    sonnet = chat.cost_usd(u, "claude-sonnet-5")
    assert chat.cost_usd(u, "gpt-5.5") == pytest.approx(5.0 + 3.0 + 0.25) and chat.metered_usd(u, "gpt-5.5") == chat.cost_usd(u, "gpt-5.5")
    assert chat.price_of("gpt-5-mini") == (0.25, 2.0, 0.025) and chat.price_of("gpt-5-mini-2026-01-01") == (0.25, 2.0, 0.025) and chat.price_of("gpt-5") == (1.25, 10.0, 0.125)
    # a model nobody has priced: the cap still counts it (at the default model's rate) and billed is not invented
    assert chat.price_of("some-local-model") is None and chat.metered_usd(u, "some-local-model") == sonnet and chat.cost_usd(u, "some-local-model") == 0
    monkeypatch.setenv("ARCHITECT_PRICE_IN", "2"); monkeypatch.setenv("ARCHITECT_PRICE_OUT", "8")
    assert chat.cost_usd(u, "some-local-model") == pytest.approx(2.0 + 0.8 + 0.1) and chat.cost_usd(u, "gpt-5.5") == pytest.approx(2.0 + 0.8 + 0.1)
    assert chat.cost_usd(u, "claude-sonnet-5") == sonnet                                                    # Claude keeps its own table
    # a flat-rate subscription bills nothing per call, and the cap still counts
    for k in ("ARCHITECT_PRICE_IN", "ARCHITECT_PRICE_OUT"):
        monkeypatch.delenv(k)
    from anaplan_architect.codex import CodexClient
    assert CodexClient.flat_rate is True and chat.cost_usd(u, "gpt-5.5", flat=True) == 0 and chat.metered_usd(u, "gpt-5.5") > 0
    assert chat.cost_usd(u, "claude-sonnet-5", flat=True) == sonnet and chat.cost_usd(u, "gpt-6.1-sol") == pytest.approx(2.0 + 1.0 + 0.05)
    # the Responses route sends an output limit sized above the answer, and drops it for an endpoint that refuses it
    from anaplan_architect.openai_compat import ResponsesClient
    sent = []

    class Inner:
        def __init__(self, refuse=False): self.responses = self; self.refuse = refuse

        def create(self, **kw):
            sent.append(kw)
            if self.refuse and "max_output_tokens" in kw:
                raise ValueError("Unknown parameter: 'max_output_tokens'")
            return iter(())
    monkeypatch.delenv("OPENAI_MAX_OUTPUT_TOKENS", raising=False)
    ResponsesClient("gpt-5.5", inner=Inner()).stream(system="s", messages=[{"role": "user", "content": "q"}], max_tokens=8000)
    assert sent[-1]["max_output_tokens"] == 32000
    cl = ResponsesClient("gpt-5.5", inner=Inner(refuse=True))
    cl.stream(system="s", messages=[{"role": "user", "content": "q"}], max_tokens=8000)
    assert "max_output_tokens" not in sent[-1] and cl.send_limit is False


def test_low_plain_errors_odd_names_and_what_a_passer_by_is_told(s):
    app, model, c, ids = s
    alice = c["alice"]
    li = (FX / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    odd = TestClient(app, raise_server_exceptions=False, cookies=alice.cookies, headers={"x-csrf": alice.cookies.get("csrf")})
    for name in ("..", ".", "../../x.csv", "a\\..\\b.csv", "x" * 400 + ".csv"):
        r = odd.post("/api/estates", data={"name": "odd", "model_names": ["Caldergate Planning"]}, files=[("line_items", (name, li, "text/csv"))])
        assert r.status_code in (200, 400), (name, r.status_code, r.text[:200])
    from anaplan_architect.web import model_error
    code, msg = model_error(RuntimeError("upstream said: the key for org-12345 at https://internal.example/v1 was refused"))
    assert code == 502 and "org-12345" not in msg and "internal.example" not in msg and "log" in msg
    assert TestClient(app).get("/health").json() == {"status": "ok"}
    assert set(alice.get("/health").json()) == {"status", "provider", "tracing"}                      # how many workspaces the instance holds is the admin's
    assert set(c["admin"].get("/health").json()) == {"status", "provider", "tracing", "estates"}
    assert "address" in c["admin"].get("/api/auth/me").json() and "address" not in alice.get("/api/auth/me").json()
