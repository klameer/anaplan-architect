"""v0.2 P6: what a container needs that a laptop does not: an admin made from the environment on first start, an
open single-user run when the port is published to localhost only, and the demo written on first start."""
import sys, pathlib, json
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "ARCHITECT_OPEN", "ARCHITECT_ADMIN_USER", "ARCHITECT_ADMIN_PASSWORD", "ARCHITECT_DEMO", "ARCHITECT_NOTICE"):
        monkeypatch.delenv(k, raising=False)


def test_a_network_bound_instance_gets_its_admin_from_the_environment_once(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHITECT_ADMIN_USER", "karim"); monkeypatch.setenv("ARCHITECT_ADMIN_PASSWORD", "a long enough password"); monkeypatch.setenv("ARCHITECT_DEMO", "1")
    app = create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0")
    c = TestClient(app)
    me = c.get("/api/auth/me").json()
    assert me["accounts"] is True and me["closed"] is False and me["open"] is False and me["user"] is None and "test instance" in me["notice"]
    assert c.get("/api/estates").status_code == 401
    assert c.post("/api/auth/login", json={"email": "karim", "password": "a long enough password"}).json()["user"]["role"] == "owner"
    # the demo was written for that admin on first start
    assert sorted(e["name"] for e in c.get("/api/estates").json()) == ["Caldergate Distribution Group", "Caldergate Stores"]
    # a restart with a different password in the environment changes nothing: the admin exists
    monkeypatch.setenv("ARCHITECT_ADMIN_PASSWORD", "another long password")
    c2 = TestClient(create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0"))
    assert c2.post("/api/auth/login", json={"email": "karim", "password": "another long password"}).status_code == 401
    assert c2.post("/api/auth/login", json={"email": "karim", "password": "a long enough password"}).status_code == 200
    assert len(c2.get("/api/estates").json()) == 2                     # and the demo is not written twice


def test_open_single_user_container_and_demo_on_first_start(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHITECT_OPEN", "1"); monkeypatch.setenv("ARCHITECT_DEMO", "1"); monkeypatch.setenv("ARCHITECT_NOTICE", "Internal instance of the planning team.")
    c = TestClient(create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0"))
    me = c.get("/api/auth/me").json()
    assert me["open"] is True and me["closed"] is False and me["notice"].startswith("Internal instance of the planning team. Whoever runs this instance can see usage figures for each login") and "Tracing" not in me["notice"]
    assert [e["id"] for e in c.get("/api/estates").json()] == ["caldergate-demo", "caldergate-stores-demo"]
    assert c.get("/health").json()["status"] == "ok"
    # without ARCHITECT_OPEN the same bind is closed until an admin exists
    monkeypatch.delenv("ARCHITECT_OPEN")
    c3 = TestClient(create_app(tmp_path / "other", client_factory=lambda: None, host="0.0.0.0"))
    assert c3.get("/api/auth/me").json()["closed"] is True and c3.get("/api/estates").status_code == 503


def test_a_stranger_gets_the_two_libraries_at_the_pinned_commits_everywhere():
    """Review 2026-11-13, item 7, and security review S9. pyproject named anaplan-grammar and anaplan-estate with no
    version or source (neither is on PyPI) and pins.json pointed at folders on one machine; then a tag, which can be
    moved. One pin, said the same way in pyproject, pins.json, the Dockerfile and the README: the commit each release
    tag names. Everything else the image installs is held to the versions the tests ran against (constraints.txt)."""
    import json, pathlib, re, tomllib
    root = pathlib.Path(__file__).resolve().parents[1]
    pins = json.loads((root / "pins.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps = project["dependencies"]
    docker, readme = (root / "Dockerfile").read_text(encoding="utf-8"), (root / "README.md").read_text(encoding="utf-8")
    for name, arg in (("anaplan-grammar", "GRAMMAR_REF"), ("anaplan-estate", "ESTATE_REF")):
        tag, url, sha = pins[name]["tag"], pins[name]["url"], pins[name]["sha"]
        assert re.fullmatch(r"v\d+\.\d+\.\d+", tag) and re.fullmatch(r"[0-9a-f]{40}", sha) and url == f"https://github.com/klameer/{name}" and tag == "v" + pins[name]["version"]
        assert f"{name} @ git+{url}@{sha}" in deps, deps
        assert f"ARG {arg}={sha}" in docker and f"git+{url}@${{{arg}}}" in docker
        assert url in readme and tag.lstrip("v") in readme and sha[:12] in readme
    assert "git" in readme.lower() and "tool.hatch.metadata" in (root / "pyproject.toml").read_text(encoding="utf-8")
    # the image installs everything else at fixed versions
    cons = {ln.split("==")[0].lower().replace("_", "-"): ln.split("==")[1] for ln in (root / "constraints.txt").read_text(encoding="utf-8").split() if "==" in ln}
    assert "-c constraints.txt" in docker and "constraints.txt" in docker.split("COPY pyproject.toml")[1].splitlines()[0]
    wanted = {re.split(r"[\[<>=!~ ]", d, 1)[0].lower().replace("_", "-") for group in project["optional-dependencies"].values() for d in group} - {"playwright"}
    assert wanted <= set(cons), sorted(wanted - set(cons))
    assert all(re.fullmatch(r"[0-9][0-9A-Za-z.]*", v) for v in cons.values()) and len(cons) > 25


def test_the_image_keeps_the_store_on_the_volume_railway_attaches():
    """Review 2026-11-13, item 7: railway.json cannot declare a volume, so the image reads where Railway mounted one."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    docker = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "--data ${RAILWAY_VOLUME_MOUNT_PATH:-${ARCHITECT_DATA}}" in docker and 'VOLUME ["/data"]' in docker
    assert "RAILWAY_VOLUME_MOUNT_PATH" in (root / "README.md").read_text(encoding="utf-8")


def _hosted(tmp_path, monkeypatch, **env):
    from anaplan_architect import envfile, codex
    monkeypatch.setattr(envfile, "candidates", lambda: []); monkeypatch.setattr(codex, "available", lambda: False)
    for k in ("ANTHROPIC_API_KEY", "ARCHITECT_OPEN", "ARCHITECT_DEMO", "ARCHITECT_NOTICE", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "ARCHITECT_HOSTED", "ARCHITECT_MAX_UPLOAD_MB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARCHITECT_ADMIN_USER", "admin"); monkeypatch.setenv("ARCHITECT_ADMIN_PASSWORD", "a long enough password")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from anaplan_architect.web import create_app
    app = create_app(tmp_path / "data", client_factory=lambda: None, host="0.0.0.0")
    return app, TestClient(app)


def test_hosted_mode_secure_cookies_hsts_no_api_docs_and_nothing_for_the_anonymous(tmp_path, monkeypatch):
    """Security review 2026-11-13, S4 and S8. Behind a proxy the app sees plain http, so the session cookie went out
    without Secure. ARCHITECT_HOSTED=1 forces Secure cookies, adds HSTS and turns the API docs off. And before signing
    in, a caller learns the notice and that a login is needed: not the data folder, the bind, the provider, the model,
    the endpoint or a tracer's error text."""
    app, c = _hosted(tmp_path / "plain", monkeypatch)
    r = c.post("/api/auth/login", json={"email": "admin", "password": "a long enough password"})
    assert r.status_code == 200 and "secure" not in r.headers["set-cookie"].lower() and "strict-transport-security" not in r.headers
    anon = TestClient(app).get("/api/auth/me").json()
    assert set(anon) <= {"notice", "open", "closed", "accounts", "user", "console_hint", "demo"} and anon["user"] is None and anon["accounts"] is True, sorted(anon)
    full = c.get("/api/auth/me").json()                                    # the same login, signed in, sees its settings page's facts
    assert full["user"]["role"] == "owner" and {"data_dir", "provider", "model", "tracing", "bind"} <= set(full)
    member_pw = c.post("/api/admin/users", headers={"x-csrf": c.cookies.get("csrf")}, json={"username": "ann", "name": "Ann", "demo": False}).json()["password"]
    ann = TestClient(app); ann.post("/api/auth/login", json={"email": "ann", "password": member_pw})
    assert "data_dir" not in ann.get("/api/auth/me").json() and "provider" in ann.get("/api/auth/me").json()      # the folder on the server's disk is the admin's to see
    assert c.get("/openapi.json").status_code == 200                       # not hosted: the API docs are there
    app, c = _hosted(tmp_path / "hosted", monkeypatch, ARCHITECT_HOSTED="1")
    r = c.post("/api/auth/login", json={"email": "admin", "password": "a long enough password"})
    cookies = r.headers.get_list("set-cookie")
    assert len(cookies) == 2 and all("secure" in x.lower() for x in cookies) and any("httponly" in x.lower() for x in cookies)
    assert "max-age=" in r.headers["strict-transport-security"] and "max-age=" in TestClient(app).get("/health").headers["strict-transport-security"]
    assert TestClient(app).get("/openapi.json").status_code == 404 and TestClient(app).get("/docs").status_code == 404 and TestClient(app).get("/redoc").status_code == 404
    assert app.state.hosted is True


def test_sign_in_is_throttled_and_costs_the_same_for_a_name_that_exists_or_not(tmp_path, monkeypatch):
    """Security review 2026-11-13, S5. Any number of passwords could be tried, and a wrong password for a real login
    cost two password hashes where an unknown name cost one, which tells which names exist."""
    import hashlib
    app, c = _hosted(tmp_path, monkeypatch)
    real = hashlib.scrypt; n = {"calls": 0}
    def counted(*a, **kw):
        n["calls"] += 1
        return real(*a, **kw)
    monkeypatch.setattr(hashlib, "scrypt", counted)
    cost = {}
    for who in ("admin", "nobody-here"):
        n["calls"] = 0
        assert TestClient(app).post("/api/auth/login", json={"email": who, "password": "wrong password 1"}).status_code == 401
        cost[who] = n["calls"]
    assert cost["admin"] == cost["nobody-here"] == 1, cost
    # five wrong passwords for one name: the sixth is refused without being looked at, even when it is right
    for i in range(4):
        assert TestClient(app).post("/api/auth/login", json={"email": "admin", "password": f"wrong {i} wrong {i}"}).status_code == 401
    n["calls"] = 0
    r = TestClient(app).post("/api/auth/login", json={"email": "admin", "password": "a long enough password"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "too many" in r.json()["detail"] and n["calls"] == 0
    assert TestClient(app).post("/api/auth/login", json={"email": "ADMIN ", "password": "a long enough password"}).status_code == 429       # the same name, however it is typed
    # the wait passes: the right password works again and clears the count
    from anaplan_architect.orac import auth
    app.state.db.run("UPDATE login_attempts SET at = '2020-01-01T00:00:00'")
    assert TestClient(app).post("/api/auth/login", json={"email": "admin", "password": "a long enough password"}).status_code == 200
    assert app.state.db.one("SELECT COUNT(*) AS n FROM login_attempts WHERE key='u:admin'")["n"] == 0
    # many names from one address are stopped too
    for i in range(auth.MAX_FAILS_PER_ADDRESS):
        TestClient(app).post("/api/auth/login", json={"email": f"guess{i}", "password": "wrong wrong wrong"})
    assert TestClient(app).post("/api/auth/login", json={"email": "someone-new", "password": "wrong wrong wrong"}).status_code == 429


def test_no_request_and_no_archive_can_ask_for_unbounded_memory(tmp_path, monkeypatch):
    """Security review 2026-11-13, S6. A request body had no size limit, a document was read whole before its size was
    looked at, a Word file's XML and a backup's tables were unzipped whatever size they claimed."""
    import io, zipfile
    from anaplan_architect.orac import documents as docsmod, backup
    app, c = _hosted(tmp_path, monkeypatch, ARCHITECT_MAX_UPLOAD_MB="1")
    c.post("/api/auth/login", json={"email": "admin", "password": "a long enough password"}); c.headers.update({"x-csrf": c.cookies.get("csrf")})
    li = (pathlib.Path(__file__).parent / "fixtures" / "estate" / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    eid = c.post("/api/estates", data={"name": "W", "model_names": ["P"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()["id"]
    big = b"x" * (2 * 1024 * 1024)
    r = c.post(f"/api/estates/{eid}/documents", files=[("files", ("big.md", big, "text/markdown"))])
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert c.post("/api/estates", data={"name": "Big", "model_names": ["P"]}, files=[("line_items", ("Line Items.csv", big, "text/csv"))]).status_code == 413
    assert c.post("/api/estates/restore", files={"file": ("e.zip", big, "application/zip")}).status_code == 413
    # a Word file whose document.xml claims to unzip to more than a document may hold is refused before it is unzipped
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"<w:document>" + b" " * (docsmod.MAX_UNZIPPED + 1024) + b"</w:document>")
    assert len(buf.getvalue()) < 200_000                                    # small on the wire, large once opened
    secs, problem, _ext = docsmod.read_file("bomb.docx", buf.getvalue())
    assert secs == [] and "too large" in problem
    # a backup whose tables or files claim more than the limit is refused before anything is read
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps({"kind": backup.KIND, "format": backup.FORMAT, "estate_id": "e-1", "name": "E"}))
        z.writestr("tables/notes.json", b"[" + b" " * (backup.MAX_TABLE_BYTES + 1024) + b"]")
    p = tmp_path / "bomb.zip"; p.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="too large"):
        backup.inspect_archive(p)
