"""Chat with an estate of Anaplan models in a browser, over the Orac store.

  anaplan-architect serve --data ./data [--port 8765]

An estate is a register of models (name, purpose, owner, aliases) and a
history of snapshots: the export files the estate is read from. Uploads stage
into a draft snapshot, are validated file by file, parsed on request, reviewed
for coverage, then activated; a failed parse leaves the previous snapshot
serving. Conversations run over the active snapshot and record its id.

Layout under --data:
  orac.db                              estates, models, snapshots, parse runs, audit
  blobs/aa/bb/<sha256>                 every uploaded export, once
  estates/<id>/snapshots/<sid>/        a snapshot's files as the engine reads them
  estates/<id>/.architect/             workspace (statuses, memories, transcripts)
  estates/<id>/{meta.json,models/}     the pre-Orac layout, imported once at startup and left in place
"""
from __future__ import annotations
import datetime, json, os, re, shutil, tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from .store import Workspace
from .questions import suggested
from . import envfile
from .orac.db import Db
from .orac.blobs import BlobStore
from .orac.snapshots import Snapshots, Reparsing
from .orac.jobs import Jobs
from .orac.legacy import import_legacy
from .orac import estates as reg
from .orac import auth
from .orac import notes as notesmod, conversations as convs, findings_state as fstate
from .orac.bridge import Bridge, import_legacy_state
from .orac import objects as objmod
from .orac import deps as depsmod, plan as planmod
from .orac import freshness as freshmod, backup as backupmod, dims as dimsmod, checks as checksmod
from .orac import documents as docsmod, lindex, demo as demomod, access
from .orac.evidence import cite_id, note_provenance, NOTE_ID, SECTION_ID

OPEN_PATHS = {"/api/auth/me", "/api/auth/login", "/health"}
SESSIONS_MAX = 32          # live conversations kept in memory; the oldest idle ones go, and come back from the store on their next message
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MAX_QUESTION_CHARS = 8000
TRACE_LEVELS = ("off", "structure", "content")
TRACE_THEIR_OWN = "what a login sends to the tracer is their own choice, made in their own Settings: it cannot be set for them"
# What the browser may load: the app's own files, inline styles (React and the diagrams set them), the two font hosts.
# No image, script, frame or request to any other origin: text the model wrote cannot make the page call out.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
       "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = {"content-security-policy": CSP, "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "x-frame-options": "DENY"}
NOTICE = ("This is a test instance. Access can be withdrawn at any time, and the instance may be reset. What you upload is your responsibility: "
          "upload only what you are allowed to share, and keep your own copy.")
CONSOLE_HINT = ("this server has no accounts yet. Create the owner from its console: "
                "anaplan-architect users create --data <DATA> --owner --email you@example.com --name \"Your name\"")

OLD_KEYS = ("modules", "line_items", "calculated", "cells", "parse_rate", "patterns", "unreferenced")


def _aliases(text: str) -> dict[str, str]:
    """'phrase=Model; phrase=Model' -> {phrase: Model}."""
    out = {}
    for part in (text or "").split(";"):
        k, _, v = part.partition("=")
        if k.strip() and v.strip():
            out[k.strip()] = v.strip()
    return out


def _alias_list(v) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.replace(",", ";").split(";") if x.strip()]
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def create_app(data: str | Path, api_key: str | None = None, model_id: str = "claude-sonnet-5", client_factory=None, host: str = "127.0.0.1",
               tracer=None) -> FastAPI:
    envfile.load()
    from .orac import telemetry
    from .provider import resolve
    data = Path(data); (data / "estates").mkdir(parents=True, exist_ok=True)
    held: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if held.get("jobs") is not None:             # the parse jobs stop with the server
            held["jobs"].shutdown()
    # ARCHITECT_HOSTED=1: this instance sits behind a proxy that ends TLS (Railway, a company gateway). Cookies are then
    # always Secure, HSTS is sent, the forwarded scheme and address are believed, and the API's own docs pages are off.
    hosted = os.environ.get("ARCHITECT_HOSTED", "").strip().lower() in ("1", "true", "yes")
    app = FastAPI(title="/architect", lifespan=lifespan, **({"docs_url": None, "redoc_url": None, "openapi_url": None} if hosted else {}))
    app.state.data = data
    app.state.host = host
    app.state.hosted = hosted
    try:
        app.state.max_body = max(1, int(os.environ.get("ARCHITECT_MAX_UPLOAD_MB") or 200)) * 1024 * 1024
    except ValueError:
        app.state.max_body = 200 * 1024 * 1024
    app.state.backend = resolve(api_key, None if model_id == "claude-sonnet-5" else model_id)
    app.state.api_key = app.state.backend["client_kw"].get("api_key")
    app.state.model_id = app.state.backend["model"] or model_id
    app.state.provider = app.state.backend["provider"]
    app.state.tracer = tracer if tracer is not None else telemetry.default(refresh=True)   # after envfile.load: the keys may sit in .env
    app.state.client_factory = client_factory
    app.state.summaries = client_factory is None and app.state.provider != "none"      # document cards are summarised by the model when the server has one

    db = Db(data / "orac.db")
    blobs = BlobStore(data / "blobs", db)
    snaps = Snapshots(db, blobs, data, subprocess=os.environ.get("ARCHITECT_INLINE_PARSE", "") != "1" and client_factory is None)
    jobs = Jobs(snaps)
    snaps.refresher = jobs.refresh           # a stale parse cache is rebuilt in the background; requests answer 409 until it is
    ws_id = reg.default_workspace(db)
    app.state.db, app.state.blobs, app.state.snaps, app.state.jobs, app.state.workspace_id = db, blobs, snaps, jobs, ws_id
    app.state.legacy = import_legacy(db, blobs, snaps, data, ws_id)
    held["jobs"] = jobs

    # ---------- identity: who is asking, and may they ----------
    # A closed system: nobody creates an account from the web. The owner is made from the server console
    # (`anaplan-architect users create --owner`); every other login is created by the admin, from the admin panel or the console.
    # With no accounts at all, a server bound to localhost stays open (one person, one machine) and a
    # server bound to the network serves nothing but the message saying how to create the owner.
    # ARCHITECT_OPEN=1 says the same of a container whose port is published to localhost only: one trusted person, no login.
    loopback = app.state.host in ("127.0.0.1", "localhost", "::1") or os.environ.get("ARCHITECT_OPEN", "").strip() == "1"
    # A hosted instance has no console to create the admin from: ARCHITECT_ADMIN_USER and ARCHITECT_ADMIN_PASSWORD
    # create it on first start, once, while there are no logins at all.
    boot_user, boot_pw = os.environ.get("ARCHITECT_ADMIN_USER", "").strip(), os.environ.get("ARCHITECT_ADMIN_PASSWORD", "")
    app.state.bootstrap = None
    if boot_user and boot_pw and auth.no_accounts(db):
        try:
            app.state.bootstrap = auth.create_owner(db, ws_id, boot_user, os.environ.get("ARCHITECT_ADMIN_NAME", "") or boot_user, boot_pw)
        except (ValueError, PermissionError) as ex:
            print(f"could not create the admin from ARCHITECT_ADMIN_USER: {ex}")
    app.state.loopback = loopback

    @app.middleware("http")
    async def headers(request: Request, call_next):
        # no request may carry more than the instance allows: said by its Content-Length, and a body with none is refused
        if request.method in MUTATING:
            size = request.headers.get("content-length")
            if size is None and "chunked" in request.headers.get("transfer-encoding", "").lower():
                response = JSONResponse({"detail": "send the request with a Content-Length"}, status_code=411)
            elif size is not None and (not size.isdigit() or int(size) > app.state.max_body):
                response = JSONResponse({"detail": f"that upload is too large: this instance takes up to {app.state.max_body // (1024 * 1024)} MB in one request"}, status_code=413)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if app.state.hosted:
            response.headers.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
        return response

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request.state.user = auth.user_for_token(db, request.cookies.get("session"))
        path = request.url.path
        if path.startswith("/api/") and path not in OPEN_PATHS:
            if auth.no_accounts(db):
                if not loopback:
                    return JSONResponse({"detail": CONSOLE_HINT, "auth": "closed"}, status_code=503)
            else:
                if request.state.user is None:
                    return JSONResponse({"detail": "sign in to use this server", "auth": "required"}, status_code=401)
                if request.method in MUTATING:
                    want = request.cookies.get("csrf")
                    if not want or request.headers.get("x-csrf") != want:
                        return JSONResponse({"detail": "missing or stale CSRF token: reload the page and try again"}, status_code=403)
                # the one place membership is checked: a path that names a workspace, or anything that lives in one, is
                # answered only to a member. To anyone else it does not exist.
                scoped, eid = access.estate_for(db, path, _live_citation_estate)
                admin_delete = request.method == "DELETE" and request.state.user["role"] == "owner" and path.rstrip("/") == f"/api/estates/{eid}"
                if scoped and eid is not None and not admin_delete and not access.is_member(db, request.state.user, eid):
                    return JSONResponse({"detail": "nothing here by that id"}, status_code=404)
        return await call_next(request)

    def _live_citation_estate(cid: str) -> str | None:
        for s in list(getattr(app.state, "sessions", {}).values()):
            if s.ev.resolve(cid) is not None:
                return s.w.estate_id
        return None

    def who(request: Request) -> str | None:
        u = getattr(request.state, "user", None)
        return u["id"] if u else None

    def owner(request: Request) -> dict:
        u = getattr(request.state, "user", None)
        if auth.no_accounts(db):
            raise HTTPException(409, CONSOLE_HINT)
        if not u or u["role"] != "owner":
            raise HTTPException(403, "the owner of this workspace does that")
        return u

    def _operator_notice() -> str:
        """What whoever runs this instance can see, said before anyone uploads: usage figures always; with tracing, what
        goes to the trace store."""
        t = app.state.tracer
        out = "Whoever runs this instance can see usage figures for each login: sign-ins, and counts of workspaces, uploads, documents, questions and spend."
        if t.enabled:
            out += (" Tracing to LangSmith is set up here. Your questions are not sent to it: nothing is, unless you turn that on for yourself in Settings. "
                    "The admin's own questions are traced.")
        return out

    def _me(request: Request) -> dict:
        wsr = db.one("SELECT id, name, created FROM workspaces WHERE id=?", ws_id)
        none = auth.no_accounts(db)
        user = getattr(request.state, "user", None)
        out = {"notice": (os.environ.get("ARCHITECT_NOTICE") or NOTICE) + " " + _operator_notice(), "demo": bool(demomod.root()),
               "open": none and loopback, "closed": none and not loopback, "accounts": not none, "user": user}
        if none and not loopback:
            out["console_hint"] = CONSOLE_HINT
        if not user and not (none and loopback):         # nobody signed in on an instance with logins: what the sign-in page needs, nothing about the server
            return out
        out |= {"workspace": wsr, "provider": app.state.provider, "model": app.state.model_id, "endpoint": app.state.backend.get("endpoint") or "",
                "provider_reason": app.state.backend.get("reason") or "", "tracing": app.state.tracer.status(), "host": request.url.hostname, "console_hint": CONSOLE_HINT}
        out["trace"] = _trace(user)
        if not user or user.get("role") == "owner":      # where the store is on the server's disk, and what it is bound to: the admin's to see
            out |= {"data_dir": str(data.resolve()), "bind": app.state.host}
        return out

    def _sign_in(response: Response, request: Request, token: str) -> None:
        secure = app.state.hosted or request.url.scheme == "https"      # behind a proxy the app sees http: hosted mode says the outside is https
        response.set_cookie("session", token, httponly=True, samesite="lax", secure=secure, max_age=auth.SESSION_DAYS * 86400, path="/")
        response.set_cookie("csrf", auth.csrf_token(), httponly=False, samesite="lax", secure=secure, max_age=auth.SESSION_DAYS * 86400, path="/")

    @app.get("/api/auth/me")
    def auth_me(request: Request):
        return _me(request)

    @app.post("/api/auth/login")
    def auth_login(request: Request, response: Response, body: dict):
        try:
            u, token = auth.login(db, body.get("email", ""), body.get("password", ""), address=request.client.host if request.client else None)
        except auth.TooManyAttempts as ex:
            raise HTTPException(429, f"too many failed sign-ins: try again in {max(1, ex.retry_after // 60)} minute{'s' if ex.retry_after >= 120 else ''}", headers={"retry-after": str(ex.retry_after)})
        except PermissionError as ex:
            raise HTTPException(401, str(ex))
        _sign_in(response, request, token)
        request.state.user = u
        return _me(request)

    @app.post("/api/auth/logout")
    def auth_logout(request: Request, response: Response):
        auth.logout(db, request.cookies.get("session"))
        response.delete_cookie("session", path="/"); response.delete_cookie("csrf", path="/")
        request.state.user = None
        return {"ok": True}

    # ---------- the admin panel (v0.2 P5): the admin creates every login; nobody signs up ----------
    def _admin_rows() -> list[dict]:
        return auth.admin_table(db, ws_id)

    @app.get("/api/admin/users")
    def admin_users(request: Request):
        owner(request)
        rows = _admin_rows()
        for r in rows:                                    # each login's own tracing level, shown, never set from here
            r["trace_level"] = _trace(r)["level"]
        return {"users": rows, "default_cap_usd": auth.default_cap(),
                "totals": {"logins": len(rows), "questions": sum(r["questions"] for r in rows), "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
                           "metered_usd": round(sum(r["metered_usd"] for r in rows), 4), "workspaces": db.one("SELECT COUNT(*) AS n FROM estates")["n"]},
                "note": "metered is what the tokens cost at list price; on a flat-rate route nothing is billed, and the cap still counts the metered amount"}

    @app.post("/api/admin/users")
    def admin_create_user(request: Request, body: dict):
        """A new login: the admin picks the username and either sets a password or lets one be generated; it is shown once."""
        u = owner(request)
        if "trace_level" in body:
            raise HTTPException(400, TRACE_THEIR_OWN)
        pw = (body.get("password") or "").strip() or auth.generate_password()
        cap = body.get("cap_usd", "default")
        try:
            new = auth.create_user(db, ws_id, body.get("username") or body.get("email") or "", body.get("name") or "", pw, role="member", by=u["id"],
                                   cap_usd=("default" if cap in ("default", "") else (None if cap is None else float(cap))))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        out = {"user": new, "password": pw, "note": "hand over the username and this password; it is not shown again"}
        if body.get("demo", True) and demomod.root():
            out["demo"] = demo_reset(new["id"])["workspaces"]
        return out

    @app.patch("/api/admin/users/{uid}")
    def admin_update_user(request: Request, uid: str, body: dict):
        u = owner(request)
        if "trace_level" in body:
            raise HTTPException(400, TRACE_THEIR_OWN)
        try:
            kw = {}
            if "cap_usd" in body:
                kw["cap_usd"] = None if body["cap_usd"] in (None, "") else float(body["cap_usd"])
            out = {"user": auth.update_account(db, uid, u["id"], disabled=body.get("disabled"), role=body.get("role"), **kw)}
            if body.get("reset_password"):
                pw = (body.get("password") or "").strip() or auth.generate_password()
                auth.set_password(db, uid, pw, by=u["id"])
                out["password"] = pw
            return out
        except KeyError:
            raise HTTPException(404, "no such login")
        except ValueError as ex:
            raise HTTPException(400, str(ex))

    @app.post("/api/auth/password")
    def auth_password(request: Request, response: Response, body: dict):
        u = getattr(request.state, "user", None)
        if not u:
            raise HTTPException(401, "sign in first")
        try:
            auth.change_password(db, u["id"], body.get("old", ""), body.get("new", ""))
            _, token = auth.login(db, u["email"], body.get("new", ""))
        except PermissionError as ex:
            raise HTTPException(403, str(ex))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        _sign_in(response, request, token)
        return {"ok": True}

    @app.patch("/api/workspace")
    def patch_workspace(request: Request, body: dict):
        owner(request)
        name = (body.get("name") or "").strip()
        if name:
            db.run("UPDATE workspaces SET name=? WHERE id=?", name[:120], ws_id)
        return db.one("SELECT id, name, created FROM workspaces WHERE id=?", ws_id)

    app.state.workspaces: dict[tuple[str, str], Workspace] = {}     # (estate id, snapshot id) -> workspace; a held conversation reads its own snapshot
    app.state.sessions: dict[str, "Session"] = {}                   # cid -> live Session (built on first use from the store)
    from .chat import Session
    # pre-store state (memories.json, statuses.json, transcripts/*.jsonl) becomes notes, finding state and conversations, once
    app.state.legacy_state = {e["id"]: import_legacy_state(db, e["id"], data / "estates" / e["id"] / ".architect", app.state.model_id)
                              for e in reg.list_estates(db, ws_id, include_archived=True)}

    # ---------- helpers ----------
    def estate(eid: str) -> dict:
        e = reg.get_estate(db, eid)
        if not e:
            raise HTTPException(404, "no such estate")
        return e

    def snapshot(sid: str) -> dict:
        try:
            return snaps.get(sid)
        except KeyError:
            raise HTTPException(404, "no such snapshot")

    def active_sid(eid: str) -> str | None:
        act = db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)
        return act["id"] if act else None

    def run_of(sid: str):
        """A snapshot's parsed estate for a request: 404 when the snapshot is gone, 409 while its exports are being re-read
        (the page asks again in a moment), 409 with the reason when they cannot be read."""
        try:
            return snaps.estate_run(sid)
        except KeyError:
            raise HTTPException(404, "that snapshot is no longer in the store")
        except Reparsing as ex:
            raise HTTPException(409, {"message": f"{ex}; the page asks again in a moment", "reparsing": True})
        except Exception as ex:
            raise HTTPException(409, f"snapshot {sid} could not be read: {type(ex).__name__}: {ex}"[:400])

    def forget(eid: str) -> None:
        for k in [k for k in app.state.workspaces if k[0] == eid]:
            app.state.workspaces.pop(k, None)
        act = active_sid(eid)
        if act:
            snaps._forget(act)

    def forget_sessions(eid: str) -> None:
        """Every live conversation over the estate is rebuilt from the store on its next message, and re-checked against the active snapshot."""
        for k in [k for k, s in app.state.sessions.items() if s.w.estate_id == eid]:
            app.state.sessions.pop(k, None)

    def workspace(eid: str, sid: str | None = None) -> Workspace:
        """The parsed estate as one snapshot holds it: the active snapshot unless a held conversation names an earlier one.
        Workspaces are kept per (estate, snapshot), never mixed."""
        estate(eid)
        sid = sid or active_sid(eid)
        if not sid:
            raise HTTPException(409, "this estate has no active snapshot: upload exports, process the snapshot and activate it first")
        own = db.one("SELECT estate_id FROM snapshots WHERE id=?", sid)
        if not own or own["estate_id"] != eid:          # a snapshot of another workspace is never read through this one, whatever names it
            raise HTTPException(404, "that snapshot is not part of this workspace")
        cached = app.state.workspaces.get((eid, sid))
        if cached is not None:
            return cached
        er = run_of(sid)
        w = Workspace.from_run(er, data / "estates" / eid / ".architect", backend=Bridge(db, eid, sid))
        w.estate_id, w.snapshot_id = eid, sid
        lindex.ensure(db, sid, er)               # the line-item index of this snapshot, written the first time it is read
        app.state.workspaces[(eid, sid)] = w
        while len(app.state.workspaces) > 8:
            app.state.workspaces.pop(next(iter(app.state.workspaces)))
        return w

    def _conv_head(c: dict) -> dict:
        return {"id": c["id"], "title": c["title"], "created": c["created"], "updated": c["updated"], "turns": c["turns_count"], "cost_usd": c["cost_usd"],
                "snapshot": c["snapshot_id"], "archived": c["archived"], "scope": c["scope"], "branched_from": c.get("branched_from"),
                "branches": len(c.get("branches") or [])}

    def summary(eid: str) -> dict:
        e = estate(eid)
        models = reg.list_models(db, eid)
        act = snaps.active(eid)
        run = (act or {}).get("run") or {}
        stats = (run.get("stats") or {}).get("models", {})
        cov = run.get("coverage") or {}
        files: dict[str, dict] = {}
        for f in (act or {}).get("files", []):
            files.setdefault(f["model_id"], {})[f["kind"]] = {"uploaded_at": f["uploaded_at"], "original_name": f["original_name"], "bytes": f["bytes"], "problem": f["problem"]}
        w = workspace(eid) if act else None
        runs = {m.name: m for m in w.estate.models} if w else {}
        out_models = []
        for m in models:
            d = dict(m, files=files.get(m["id"], {}), coverage=cov.get(m["name"]), stats=stats.get(m["name"]))
            mr = runs.get(m["name"])
            if mr:
                f = mr.facts; a = f["actions"] or {}
                d.update({k: f[k] for k in OLD_KEYS})
                d["module_names"] = sorted(mr.model.modules)          # the page styles module and line-item names from this list
                d["cells_by_module"] = f["cells_by_module"]           # Home: the ten largest modules as (name, cells, share of the model)
                d["effort_by_module"] = f["effort_by_module"] if f["has_effort"] else []   # Home: (name, share of the effort of the model)
                d.update({"imports": a.get("imports"), "exports": a.get("exports"), "stale": a.get("stale_count"),
                          "effort_top10": f["effort_top10_share"], "agreement": f["referenced_by_check"]["agreement"]})
            out_models.append(d)
        return {"id": eid, "name": e["name"], "created": e["created"], "archived": e["archived"], "models": out_models,
                "snapshot": ({k: act[k] for k in ("id", "label", "created", "activated_at", "note")} | {"files": len(act["files"]),
                             "run": {k: run.get(k) for k in ("id", "status", "started", "finished", "error")}}) if act else None,
                "snapshots": snaps.list(eid),
                "edges": [dict(e, state=w.edge_state(e["from"], e["to"])) for e in w.estate.edges] if w else [],
                "external": {k: len(v) for k, v in w.estate.external.items()} if w else {},
                "duplicates": len(w.estate.duplicates) if w else 0, "questions": suggested(w) if w else [],
                "statuses": len(w.statuses) if w else 0, "memories": len(w.memories) if w else 0, "notes": notesmod.count(db, eid),
                "notes_flagged": notesmod.count_flagged(db, eid), "documents": docsmod.count(db, eid),
                "conversations": [_conv_head(c) for c in reversed(convs.list_conversations(db, eid, archived=False))],
                "tests": checksmod.rollup(checksmod.of(w)) if w else None,      # Home: the catalogue's totals and one line per area
                "llm": bool(app.state.client_factory) or app.state.provider != "none",
                "provider": "test" if app.state.client_factory else app.state.provider, "model": app.state.model_id}

    def _client_kw() -> dict:
        if app.state.client_factory:
            return {"client": app.state.client_factory()}
        b = app.state.backend
        if b["provider"] == "anthropic":
            return {"api_key": b["client_kw"]["api_key"]}
        if b["provider"] == "codex":
            from .codex import CodexClient
            return {"client": CodexClient(model=b["model"], reasoning_effort=os.environ.get("CODEX_REASONING") or "medium")}
        if b["provider"] != "none":                      # bedrock, azure, an OpenAI-compatible endpoint: a client of its own per session
            from .provider import client_kw
            return client_kw(b)
        raise HTTPException(503, "no LLM key: " + b.get("reason", "set ANTHROPIC_API_KEY or run `codex login`"))

    def _session_kw(eid: str, c: dict, user: str | None, sid: str) -> dict:
        """What binds a Session to the store: the recorder that keeps every turn, the retriever that finds the
        owner's notes for each question, the conversation's scope, and one honest line about the snapshot it
        reads when that is not simply the active one (held on an earlier snapshot, or a re-evaluation)."""
        scope = c.get("scope") or {}
        mid = None
        if scope.get("model"):
            m = reg.find_model(db, eid, scope["model"])
            mid = m["id"] if m else None
        act = active_sid(eid)
        note = ""
        if c.get("branched_from"):
            o = c.get("origin") or {}
            note = (f"This conversation re-evaluates an earlier one (id {c['branched_from']}, held on snapshot {o.get('snapshot_id') or 'unknown'}) against the "
                    f"current snapshot {sid}. Answer from the current estate only; do not assume the earlier answers still hold, and say when something has changed.")
        elif act and sid != act:
            note = (f"This conversation is held on snapshot {sid}, which the estate no longer reads (the active snapshot is {act}). Every tool here reads "
                    f"snapshot {sid}; answer from it, and say so if the owner asks about the current estate.")
        return {"recorder": lambda turn: convs.add_turn(db, c["id"], turn, snapshot_id=sid),     # author = turn["by"]: whoever asked, not whoever opened the session
                "retriever": lambda q: notesmod.search(db, eid, q, model_id=mid, module=scope.get("module"), limit=6),
                "scope": scope, "user": user, "cid": c["id"], "model_id": app.state.model_id, "meta": {"snapshot": sid}, "context_note": note,
                "tracer": app.state.tracer, "trace_state": _trace_state(c["id"]),
                "save_trace_state": lambda st, _cid=c["id"]: db.run("UPDATE conversations SET trace_json=? WHERE id=?", json.dumps(st), _cid)}

    def _trace_state(cid: str) -> dict | None:
        """Where this conversation lives in the trace store (its trace id and root span), once a turn has been traced."""
        row = db.one("SELECT trace_json FROM conversations WHERE id=?", cid)
        try:
            return json.loads(row["trace_json"]) if row and row["trace_json"] else None
        except ValueError:
            return None

    def _keep_session(cid: str, s: Session) -> None:
        """The live sessions, most recently used last. Once there are more than SESSIONS_MAX the oldest idle ones go (a
        session in the middle of an answer never does); an evicted conversation is rebuilt from the store on its next message."""
        app.state.sessions.pop(cid, None)
        app.state.sessions[cid] = s
        for k, other in list(app.state.sessions.items()):
            if len(app.state.sessions) <= SESSIONS_MAX:
                break
            if k != cid and not other.lock.locked():
                app.state.sessions.pop(k, None)

    def _bind(eid: str, c: dict, w: Workspace, user: str | None, title: str) -> Session:
        s = Session(w, title=title[:80], **_session_kw(eid, c, user, w.snapshot_id), **_client_kw())
        _meter(s, user)
        db.run("UPDATE conversations SET transcript_path=? WHERE id=?", str(s.path), c["id"])
        _keep_session(c["id"], s)
        return s

    def _spend_gate(uid: str | None) -> None:
        """Before any model call made for a login: refuse it when the login's ledger has reached its cap."""
        if not uid:
            return
        over = auth.over_cap(db, db.one("SELECT * FROM users WHERE id=?", uid))
        if over:
            from .chat import SpendCapReached
            raise SpendCapReached(f"this login has reached its spend cap, ${over['spent_usd']:.2f} used of ${over['cap_usd']:.2f}")

    def _spent(uid: str | None, u: dict, kind: str = "answer") -> None:
        from .chat import cost_usd, metered_usd
        auth.record_spend(db, uid, metered_usd(u, app.state.model_id), cost_usd(u, app.state.model_id), kind=kind, model=app.state.model_id,
                          tokens_in=u.get("input", 0) + u.get("cache_read", 0) + u.get("cache_write", 0), tokens_out=u.get("output", 0))

    def _meter(s: Session, uid: str | None) -> None:
        """Every model call of a session is checked against the login's cap before it is made and put on the login's
        ledger when it returns."""
        s.spend_gate = lambda: _spend_gate(uid)
        s.on_spend = lambda u: _spent(uid, u)

    def new_session(eid: str, title: str, user: str | None = None, scope: dict | None = None) -> str:
        w = workspace(eid)
        c = convs.create(db, eid, title[:200], w.snapshot_id, author=user, scope=scope or None)
        _bind(eid, c, w, user, title)
        return c["id"]

    def session_of(cid: str, user: str | None = None) -> Session:
        """The live session for a conversation, rebuilt from the store when needed. A conversation held on a
        snapshot the estate no longer reads is not answered until the owner has chosen: continue on the held
        snapshot (then it is rebuilt over that snapshot) or re-evaluate as a branch. Never silently mixed."""
        s = app.state.sessions.get(cid)
        if s is not None:
            s.user = user or s.user
            _keep_session(cid, s)
            return s
        try:
            c = convs.get(db, cid)
        except KeyError:
            raise HTTPException(404, "no such conversation")
        eid = c["estate_id"]
        st = convs.stale(db, c, active_sid(eid))
        if st and not st["acked"]:
            raise HTTPException(409, {"message": "this conversation was held on an earlier snapshot: continue it on that snapshot, or re-evaluate it "
                                      "on the current one as a linked branch", "stale": st})
        held = c["snapshot_id"] if st and st["can_continue"] else None
        w = workspace(eid, held)
        s = Session.resume_turns(w, c["turns"], title=c["title"], **_session_kw(eid, c, user, w.snapshot_id), **_client_kw())
        _keep_session(cid, s)
        return s

    async def _stage_upload(sid: str, mid: str, kind: str, up: UploadFile | None) -> dict | None:
        if not up or not up.filename:
            return None
        body = await up.read()
        if not body:
            return None
        try:
            return snaps.stage(sid, mid, kind, body, up.filename)
        except ValueError as ex:
            raise HTTPException(400, str(ex))

    async def _stage_rows(sid: str, eid: str, model_ids: list[str], model_names: list[str], line_items: list[UploadFile],
                          actions: list[UploadFile], modules: list[UploadFile], zip_file: UploadFile | None) -> list[dict]:
        """Rows are aligned by index: model_ids[i] (or a new model named model_names[i]) gets line_items[i], actions[i], modules[i]."""
        staged = []
        rows = max(len(model_ids), len(model_names), len(line_items), len(actions), len(modules))
        for i in range(rows):
            mid = model_ids[i].strip() if i < len(model_ids) else ""
            if not mid:
                name = model_names[i] if i < len(model_names) else ""
                if not name.strip():
                    li = line_items[i] if i < len(line_items) else None
                    name = (li.filename or "").rsplit(".", 1)[0] if li else ""
                if not name.strip():
                    raise HTTPException(400, f"row {i + 1}: pick a model or give the new one a name")
                m = reg.find_model(db, eid, name)
                if not m:
                    try:
                        m = reg.add_model(db, eid, name)
                    except ValueError as ex:
                        raise HTTPException(400, str(ex))
                mid = m["id"]
            else:
                m = reg.get_model(db, mid)
                if not m or m["estate_id"] != eid:
                    raise HTTPException(400, f"row {i + 1}: that model is not in this estate")
            for kind, lst in (("line_items", line_items), ("actions", actions), ("modules", modules)):
                r = await _stage_upload(sid, mid, kind, lst[i] if i < len(lst) else None)
                if r:
                    staged.append(r)
        if zip_file and zip_file.filename:
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / "estate.zip"
                with open(p, "wb") as out:
                    while True:
                        chunk = await zip_file.read(1 << 18)
                        if not chunk:
                            break
                        out.write(chunk)
                try:
                    staged += snaps.stage_zip(sid, p, make_model=lambda n: reg.add_model(db, eid, n))
                except ValueError as ex:
                    raise HTTPException(400, str(ex))
        return staged

    def _discard_estate(eid: str) -> None:
        """Everything the estate owns goes: its rows (models, snapshots, files, runs, notes, conversations, turns, decisions
        and proposals cascade; the citations its turns and notes own are removed here, they have no key to cascade on),
        the workspaces and parsed runs in memory, the plans cached per snapshot, and the folder on disk. Nothing of it
        is left to be retrieved or opened afterwards; blobs go with the caller's gc."""
        sids = [r["id"] for r in db.q("SELECT id FROM snapshots WHERE estate_id=?", eid)]
        with db.tx():
            db.run("DELETE FROM citations WHERE (owner_kind='turn' AND owner_id IN (SELECT t.id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE c.estate_id=?)) "
                   "OR (owner_kind='note' AND owner_id IN (SELECT id FROM notes WHERE estate_id=?))", eid, eid)
            reg.delete_estate(db, eid)
        forget(eid)
        forget_sessions(eid)
        for sid in sids:
            _drop_snapshot_caches(sid)
            snaps._forget(sid)
        shutil.rmtree(data / "estates" / eid, ignore_errors=True)

    # ---------- pages ----------
    static = Path(__file__).parent / "static"
    built = static / "app" / "index.html"          # the React shell, built by `npm run build` in web/ and shipped in the package
    if (static / "app" / "assets").is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/app/assets", StaticFiles(directory=str(static / "app" / "assets")), name="app-assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        if not built.exists():
            return "<!doctype html><title>/architect</title><p>The app has not been built: run <code>npm install &amp;&amp; npm run build</code> in <code>web/</code>.</p>"
        return built.read_text(encoding="utf-8")

    @app.get("/app", response_class=HTMLResponse)
    @app.get("/app/", response_class=HTMLResponse)
    def index_app():
        return index()


    # ---------- estates ----------
    @app.get("/health")
    def health():
        return {"status": "ok", "estates": len(reg.list_estates(db, ws_id, include_archived=True)), "provider": app.state.provider,
                "tracing": app.state.tracer.enabled}

    @app.get("/api/estates")
    def list_estates(request: Request, archived: bool = False):
        out = []
        for e in access.visible(db, getattr(request.state, "user", None), reg.list_estates(db, ws_id, include_archived=archived)):
            act = db.one("SELECT id, label, activated_at FROM snapshots WHERE estate_id=? AND status='active'", e["id"])
            out.append({"id": e["id"], "name": e["name"], "created": e["created"], "archived": e["archived"],
                        "models": [m["name"] for m in reg.list_models(db, e["id"], include_retired=False)], "snapshot": act, **_holds(e["id"])})
        return out

    @app.post("/api/estates")
    async def create_estate_with_files(request: Request, name: str = Form(""), model_names: list[str] = Form(...), line_items: list[UploadFile] = File(...),
                                       actions: list[UploadFile] = File(default=[]), modules: list[UploadFile] = File(default=[]), aliases: str = Form("")):
        """One request: register the models, stage their files, parse, activate. A bad export leaves nothing behind."""
        if len(model_names) != len(line_items):
            raise HTTPException(400, "one Line Items file per model name")
        al = _aliases(aliases)
        by = who(request)
        e = reg.create_estate(db, ws_id, name.strip() or f"Estate of {len(model_names)}", created_by=by)
        if by:
            access.add_member(db, e["id"], by)
        try:
            snap = snaps.create(e["id"], label="first upload", inherit=False, created_by=by)
            for i, (mn, li) in enumerate(zip(model_names, line_items)):
                mn = reg.safe_name(mn)
                if not mn or re.fullmatch(r"(?i)(line[\s_-]*items?|modules?|actions?)(\.csv)?", mn):      # a name taken from the export file, not the model
                    mn = f"Model {i + 1}"
                m = reg.find_model(db, e["id"], mn) or reg.add_model(db, e["id"], mn, aliases=[a for a, t in al.items() if reg.safe_name(t) == mn], created_by=by)
                await _stage_upload(snap["id"], m["id"], "line_items", li)
                for kind, lst in (("actions", actions), ("modules", modules)):
                    if i < len(lst):
                        await _stage_upload(snap["id"], m["id"], kind, lst[i])
            why = snaps.ready(snap["id"])
            if why:
                raise ValueError("; ".join(why))
            run = snaps.process(snap["id"])
            if run["status"] != "ok":
                raise ValueError(run["error"] or "parse failed")
            snaps.activate(snap["id"], by=by)
        except (ValueError, KeyError, HTTPException) as ex:
            _discard_estate(e["id"])
            raise HTTPException(400, f"could not read the exports: {getattr(ex, 'detail', ex)}")
        return summary(e["id"])

    @app.post("/api/estates/create")
    def create_estate_json(request: Request, body: dict | None = None):
        body = body or {}
        e = reg.create_estate(db, ws_id, (body.get("name") or "").strip(), created_by=who(request))
        if who(request):
            access.add_member(db, e["id"], who(request))
        return summary(e["id"])

    @app.get("/api/estates/{eid}")
    def get_estate(eid: str):
        return summary(eid)

    @app.patch("/api/estates/{eid}")
    def patch_estate(eid: str, body: dict):
        estate(eid)
        reg.update_estate(db, eid, name=body.get("name"), archived=body.get("archived"))
        return summary(eid)

    def _holds(eid: str) -> dict:
        """What a workspace holds, as counts: what a delete takes with it."""
        n = lambda sql: db.one(sql, eid)["n"]
        return {"documents": n("SELECT COUNT(*) AS n FROM documents WHERE estate_id=?"), "chats": n("SELECT COUNT(*) AS n FROM conversations WHERE estate_id=?"),
                "notes": n("SELECT COUNT(*) AS n FROM notes WHERE estate_id=?")}

    @app.get("/api/admin/workspaces")
    def admin_workspaces(request: Request):
        """Every workspace on the instance, for the admin: its name, who is in it and counts. Never its content."""
        owner(request)
        out = []
        for e in reg.list_estates(db, ws_id, include_archived=True):
            out.append({"id": e["id"], "name": e["name"], "created": e["created"], "archived": e["archived"],
                        "members": [r["email"] for r in db.q("SELECT u.email FROM estate_members m JOIN users u ON u.id=m.user_id WHERE m.estate_id=? ORDER BY u.email", e["id"])],
                        "models": len(reg.list_models(db, e["id"], include_retired=False)), **_holds(e["id"])})
        return {"workspaces": out}

    @app.delete("/api/estates/{eid}")
    def delete_estate(eid: str, body: dict | None = None):
        """Removes the estate: register, snapshots, runs, the materialised folders and the .architect workspace
        with its transcripts. The caller must send the estate's name back to confirm. Blobs are left for gc."""
        e = estate(eid)
        if not body or (body.get("confirm") or "").strip() != e["name"]:
            raise HTTPException(400, "type the workspace's exact name to delete it")
        _discard_estate(eid)
        return {"deleted": eid, "blobs_removed": blobs.gc()}

    # ---------- backup and restore (stage 5) ----------
    async def _save_upload(up: UploadFile, dest: Path) -> None:
        with open(dest, "wb") as out:
            while True:
                chunk = await up.read(1 << 18)
                if not chunk:
                    break
                out.write(chunk)

    @app.get("/api/estates/{eid}/backup")
    def backup_estate(request: Request, eid: str):
        """The estate as one zip: register, snapshots with their export files, notes, conversations with their turns and
        citations, decisions, proposals, transcripts and reviews. No accounts, passwords, sessions, invite codes, settings
        or audit rows leave with it."""
        from fastapi.responses import FileResponse
        from starlette.background import BackgroundTask
        e = estate(eid)
        td = tempfile.mkdtemp(prefix="architect-backup-")
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        fname = f"{(reg.safe_name(e['name']) or 'estate').replace(' ', '_')}-{eid}-{stamp}.architect.zip"
        path = backupmod.export_estate(db, blobs, data, eid, Path(td) / fname, by=who(request))
        return FileResponse(str(path), media_type="application/zip", filename=fname, background=BackgroundTask(shutil.rmtree, td, True))

    @app.post("/api/estates/restore/inspect")
    async def inspect_backup(request: Request, file: UploadFile = File(...)):
        """What a backup holds, before it is restored: name, models, counts, when it was taken, and whether its id is already here."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "backup.zip"
            await _save_upload(file, p)
            try:
                m = backupmod.inspect_archive(p)
            except ValueError as ex:
                raise HTTPException(400, str(ex))
        have = reg.get_estate(db, m["estate_id"])
        # an id already here: named only to a login that is in that workspace (or on a store with no logins)
        u = getattr(request.state, "user", None)
        mine = have and (auth.no_accounts(db) or access.is_member(db, u, have["id"]))
        m["conflict"] = ({"id": have["id"], "name": have["name"]} if mine else {"id": have["id"]}) if have else None
        return m

    @app.post("/api/estates/restore")
    async def restore_backup(request: Request, file: UploadFile = File(...), name: str = Form("")):
        """Restore a backup under its original ids, so every old citation still opens. Refuses an estate already in the store."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "backup.zip"
            await _save_upload(file, p)
            try:
                r = backupmod.import_estate(db, blobs, data, p, ws_id, by=who(request), name=name)
            except ValueError as ex:
                raise HTTPException(409 if "already in this store" in str(ex) else 400, str(ex))
        if who(request):
            access.add_member(db, r["id"], who(request))
        if r.get("active_snapshot"):                  # the archive carries no parse cache: read the exports now, so the page opens on a whole estate
            try:
                snaps.estate_run(r["active_snapshot"], block=True)
            except Exception as ex:
                raise HTTPException(409, f"restored, but its exports could not be read: {type(ex).__name__}: {ex}"[:400])
        return summary(r["id"]) | {"restore": r}

    @app.get("/api/estates/{eid}/report")
    def get_report(eid: str):
        from anaplan_estate.fleet import render_markdown
        from anaplan_estate.htmlout import md_to_html
        w = workspace(eid)
        theme = Path(__file__).parent / "static" / "report-theme-dark.css"
        css = theme.read_text(encoding="utf-8") if theme.exists() else None
        # One self-contained page with its own inline script and styles: it gets a policy of its own, which lets those
        # run and lets the page reach nothing at all (no connect, no image but data:, no frame), the app included.
        return HTMLResponse(md_to_html(render_markdown(w.estate), "Estate report", css=css, brand="ANAPLAN ESTATE REPORT"),
                            headers={"content-security-policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
                                                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @app.get("/api/estates/{eid}/state")
    def get_state(eid: str):
        w = workspace(eid)
        return {"statuses": w.statuses, "memories": w.memories}

    # ---------- models ----------
    @app.get("/api/estates/{eid}/models")
    def list_models(eid: str):
        estate(eid)
        return reg.list_models(db, eid)

    @app.post("/api/estates/{eid}/models")
    def add_model(request: Request, eid: str, body: dict):
        estate(eid)
        try:
            return reg.add_model(db, eid, body.get("name") or "", purpose=body.get("purpose") or "", owner=body.get("owner") or "",
                                 aliases=_alias_list(body.get("aliases")), created_by=who(request))
        except ValueError as ex:
            raise HTTPException(400, str(ex))

    @app.get("/api/models/{mid}")
    def get_model(mid: str):
        m = reg.get_model(db, mid)
        if not m:
            raise HTTPException(404, "no such model")
        return m

    @app.patch("/api/models/{mid}")
    def patch_model(mid: str, body: dict):
        m = reg.get_model(db, mid)
        if not m:
            raise HTTPException(404, "no such model")
        try:
            out = reg.update_model(db, mid, name=body.get("name"), purpose=body.get("purpose"), owner=body.get("owner"),
                                   aliases=_alias_list(body["aliases"]) if "aliases" in body else None, retired=body.get("retired"))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        if body.get("name") is not None or "aliases" in body:
            eid = m["estate_id"]
            forget(eid)                               # the engine reads names and aliases: rebuild on next use
            if out["name"] != m["name"]:              # a rename: live sessions, cached plans and sizes all carry the old name
                forget_sessions(eid)
                for r in db.q("SELECT id FROM snapshots WHERE estate_id=?", eid):
                    _drop_snapshot_caches(r["id"])
        return out

    # ---------- snapshots ----------
    @app.get("/api/estates/{eid}/snapshots")
    def list_snapshots(eid: str):
        estate(eid)
        return snaps.list(eid)

    @app.post("/api/estates/{eid}/snapshots")
    async def create_snapshot(request: Request, eid: str, label: str = Form(""), note: str = Form(""), fresh: bool = Form(False),
                              model_ids: list[str] = Form(default=[]), model_names: list[str] = Form(default=[]),
                              line_items: list[UploadFile] = File(default=[]), actions: list[UploadFile] = File(default=[]),
                              modules: list[UploadFile] = File(default=[]), zip: UploadFile | None = File(default=None)):
        """A draft snapshot: the active snapshot's files (unless fresh) plus whatever is uploaded here."""
        estate(eid)
        snap = snaps.create(eid, label=label, note=note, inherit=not fresh, created_by=who(request))
        await _stage_rows(snap["id"], eid, model_ids, model_names, line_items, actions, modules, zip)
        return snapshot(snap["id"])

    @app.get("/api/snapshots/{sid}")
    def get_snapshot(sid: str):
        s = snapshot(sid)
        s["running"] = jobs.running(sid)
        return s

    @app.post("/api/snapshots/{sid}/files")
    async def add_files(sid: str, model_ids: list[str] = Form(default=[]), model_names: list[str] = Form(default=[]),
                        line_items: list[UploadFile] = File(default=[]), actions: list[UploadFile] = File(default=[]),
                        modules: list[UploadFile] = File(default=[]), zip: UploadFile | None = File(default=None)):
        s = snapshot(sid)
        await _stage_rows(sid, s["estate_id"], model_ids, model_names, line_items, actions, modules, zip)
        return snapshot(sid)

    @app.delete("/api/snapshots/{sid}/files/{mid}")
    def remove_files(sid: str, mid: str, kind: str | None = None):
        snapshot(sid)
        try:
            snaps.unstage(sid, mid, kind)
        except ValueError as ex:
            raise HTTPException(409, str(ex))
        return snapshot(sid)

    @app.post("/api/snapshots/{sid}/process")
    def process_snapshot(request: Request, sid: str):
        snapshot(sid)
        try:
            run = jobs.submit(sid, by=who(request))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        return {"run": run, "snapshot": snapshot(sid)}

    @app.post("/api/snapshots/{sid}/cancel")
    def cancel_snapshot(sid: str):
        snapshot(sid)
        return {"cancelled": jobs.cancel(sid)}

    @app.post("/api/snapshots/{sid}/activate")
    def activate_snapshot(request: Request, sid: str):
        s = snapshot(sid)
        try:
            snaps.activate(sid, by=who(request))
        except ValueError as ex:
            raise HTTPException(409, str(ex))
        eid = s["estate_id"]
        forget(eid)
        forget_sessions(eid)             # every conversation held on the previous snapshot is now stale, and asks before it answers again
        review = freshmod.review_notes(db, snaps, eid, sid, by=who(request))
        try:
            docsmod.relink(db, eid, run_of(sid))     # the objects each document section names, against the estate as it is now
        except HTTPException:
            pass
        forget_state(eid)                # flagged notes carry their flag into the material
        return summary(eid) | {"review": review}

    @app.delete("/api/snapshots/{sid}")
    def delete_snapshot(request: Request, sid: str):
        """A draft, processed or failed snapshot goes at once; a superseded one only when nothing points at it (the
        response says what does). The active snapshot never goes. Its blobs go with it when nothing else holds them."""
        snapshot(sid)
        try:
            out = snaps.delete(sid, by=who(request))
        except ValueError as ex:
            raise HTTPException(409, str(ex))
        _drop_snapshot_caches(sid)
        return out

    # ---------- conversations ----------
    @app.get("/api/estates/{eid}/conversations")
    def list_conversations(eid: str, q: str | None = None, archived: bool | None = False):
        estate(eid)
        return [_conv_head(c) for c in convs.list_conversations(db, eid, q=q, archived=archived)]

    @app.post("/api/estates/{eid}/conversations")
    def start_conversation(request: Request, eid: str, body: dict | None = None):
        body = body or {}
        title = (body.get("title") or body.get("text") or "New conversation").strip()
        if body.get("text"):
            _question(body["text"])
            _cap(request)
        cid = new_session(eid, title, user=who(request), scope=body.get("scope"))
        out = {"id": cid, "title": title[:200], "turns": [], "scope": body.get("scope") or {}}
        if body.get("text"):
            out["turns"].append(_turn(cid, body["text"], who(request), _mode(request, body)))
        return out

    def _conversation(cid: str) -> dict:
        try:
            c = convs.get(db, cid)
        except KeyError:
            raise HTTPException(404, "no such conversation")
        return {"id": c["id"], "estate": c["estate_id"], "title": c["title"], "turns": c["turns"], "cost_usd": c["cost_usd"], "model": app.state.model_id,
                "snapshot": c["snapshot_id"], "scope": c["scope"], "archived": c["archived"], "created": c["created"], "updated": c["updated"],
                "branched_from": c.get("branched_from"), "origin": c.get("origin"), "branches": c.get("branches") or [],
                "stale": convs.stale(db, c, active_sid(c["estate_id"]))}

    @app.get("/api/conversations/{cid}")
    def get_conversation(cid: str):
        return _conversation(cid)

    @app.patch("/api/conversations/{cid}")
    def patch_conversation(request: Request, cid: str, body: dict):
        try:
            c = convs.get(db, cid, with_turns=False)
        except KeyError:
            raise HTTPException(404, "no such conversation")
        if body.get("continue_on_snapshot"):
            # the owner's choice for a stale conversation: keep answering on the snapshot it is held on. If the store no
            # longer has that snapshot there is nothing to continue on: it is re-bound to the active one, and the audit says so.
            act = active_sid(c["estate_id"])
            if not act:
                raise HTTPException(409, "this estate has no active snapshot")
            st = convs.stale(db, c, act)
            if st and not st["can_continue"]:
                db.run("UPDATE conversations SET snapshot_id=? WHERE id=?", act, cid)
                e = estate(c["estate_id"])
                db.audit(e["workspace_id"], "conversation.rebind", cid, {"held_on": c["snapshot_id"], "now": act, "why": "held snapshot no longer in the store"}, who(request))
            convs.ack_stale(db, cid, act, by=who(request))
            app.state.sessions.pop(cid, None)
        if any(k in body for k in ("title", "archived", "scope")):
            convs.update(db, cid, title=body.get("title"), archived=body.get("archived"), scope=body.get("scope"), by=who(request))
        s = app.state.sessions.get(cid)
        if s is not None:
            if body.get("title"):
                s.title = body["title"][:80]
            if "scope" in body:
                app.state.sessions.pop(cid, None)          # rebuilt from the store with the new scope on next use
        return _conversation(cid)

    @app.post("/api/conversations/{cid}/branch")
    def branch_conversation(request: Request, cid: str, body: dict | None = None):
        """Re-evaluate on the current snapshot as a linked branch: a new conversation on the active snapshot, pointing
        back at this one, with this one's questions returned for the page to ask again. No answer is carried over: every
        claim in the branch is made against the snapshot it names."""
        try:
            c = convs.get(db, cid, with_turns=False)
        except KeyError:
            raise HTTPException(404, "no such conversation")
        w = workspace(c["estate_id"])
        nc, qs = convs.branch(db, cid, w.snapshot_id, by=who(request), title=(body or {}).get("title"))
        _bind(c["estate_id"], nc, w, who(request), nc["title"] or "")
        return {"id": nc["id"], "title": nc["title"], "branched_from": cid, "snapshot": w.snapshot_id, "held_on": c["snapshot_id"], "questions": qs}

    @app.get("/api/turns/{tid}/plan")
    def export_plan(tid: str, format: str = "md"):
        """The build plan an answer carries, as markdown or as CSV (one row per line item, in build order)."""
        from fastapi.responses import PlainTextResponse
        from .orac import buildplan
        row = db.one("SELECT blocks_json FROM turns WHERE id=?", tid)
        plan = next((b["plan"] for b in json.loads((row or {}).get("blocks_json") or "[]") if b.get("type") == "build_plan"), None) if row else None
        if plan is None:
            raise HTTPException(404, "that answer carries no build plan")
        name = "".join(ch if ch.isalnum() else "-" for ch in (plan.get("title") or "build-plan")).strip("-")[:60] or "build-plan"
        if format == "csv":
            return PlainTextResponse(buildplan.to_csv(plan), media_type="text/csv", headers={"content-disposition": f'attachment; filename="{name}.csv"'})
        return PlainTextResponse(buildplan.to_markdown(plan), media_type="text/markdown", headers={"content-disposition": f'attachment; filename="{name}.md"'})

    @app.get("/api/conversations/{cid}/export")
    def export_conversation(cid: str, format: str = "md"):
        from fastapi.responses import PlainTextResponse
        try:
            if format == "jsonl":
                return PlainTextResponse(convs.export_jsonl(db, cid), media_type="application/x-ndjson",
                                         headers={"content-disposition": f'attachment; filename="{cid}.jsonl"'})
            return PlainTextResponse(convs.export_markdown(db, cid), media_type="text/markdown",
                                     headers={"content-disposition": f'attachment; filename="{cid}.md"'})
        except KeyError:
            raise HTTPException(404, "no such conversation")

    @app.delete("/api/conversations/{cid}")
    def delete_conversation(request: Request, cid: str):
        """Removes the conversation from the store. Its JSONL export moves to .architect/transcripts/deleted/
        rather than being erased, so a wrong click costs nothing; nothing lists or loads that folder."""
        app.state.sessions.pop(cid, None)
        c = convs.delete(db, cid, by=who(request))
        if not c:
            raise HTTPException(404, "no such conversation")
        path = Path(c["transcript_path"]) if c.get("transcript_path") else data / "estates" / c["estate_id"] / ".architect" / "transcripts" / f"{cid}.jsonl"
        if path.exists():
            trash = path.parent / "deleted"
            trash.mkdir(exist_ok=True)
            path.replace(trash / path.name)
        return {"deleted": cid, "estate": c["estate_id"]}

    # ---------- notes ----------
    @app.get("/api/estates/{eid}/notes")
    def list_notes(eid: str, q: str | None = None, type: str | None = None, status: str | None = None, model_id: str | None = None,
                   module: str | None = None, superseded: bool = False, flagged: bool = False):
        estate(eid)
        return notesmod.list_notes(db, eid, q=q, type=type, status=status, model_id=model_id, module=module, include_superseded=superseded, flagged=flagged)

    def _cite_scopes(eid: str, nid: str) -> int:
        """A note scoped to a model, a module or a line item carries that object's citation on the active snapshot, so the
        Notes page shows the evidence it rests on and the freshness check flags the note when the object moves. Citations
        minted this way are marked source_ref 'scope' and replaced whenever the note's scope changes."""
        sid = active_sid(eid)
        db.run("DELETE FROM note_sources WHERE note_id=? AND citation_id IN (SELECT id FROM citations WHERE owner_kind='note' AND owner_id=? AND source_ref='scope')", nid, nid)
        db.run("DELETE FROM citations WHERE owner_kind='note' AND owner_id=? AND source_ref='scope'", nid)
        if not sid:
            return 0
        try:
            er = snaps.estate_run(sid)
        except Exception as ex:                       # the documents stay as they are; said in the server's log, not swallowed
            print(f"documents not re-linked for {eid}: the snapshot could not be read ({type(ex).__name__}: {ex})"[:300])
            return 0
        names = {r["id"]: r["name"] for r in db.q("SELECT id, name FROM models WHERE estate_id=?", eid)}
        made = 0
        for o in db.q("SELECT scope, model_id, module, line_item FROM note_objects WHERE note_id=?", nid):
            mname = names.get(o["model_id"] or "")
            m = objmod.find_model(er, mname) if mname else None
            if m is None:
                continue
            if o["scope"] == "model":
                kind, ref = "model", m.name
            elif o["scope"] == "module" and o["module"] in m.model.modules:
                kind, ref = "module", o["module"]
            elif o["scope"] == "line_item" and (o["module"], o["line_item"]) in m.model.line_items:
                kind, ref = "line_item", f"{o['module']}.{o['line_item']}"
            else:
                continue
            cid = cite_id(sid, kind, m.name, ref)
            db.run("INSERT OR IGNORE INTO citations(id, owner_kind, owner_id, provenance, snapshot_id, model_id, kind, object_ref, source_ref, payload_json) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", cid, "note", nid, "observed", sid, m.name, kind, ref, "scope", json.dumps({"name": ref}))
            db.run("INSERT OR IGNORE INTO note_sources(note_id, citation_id) VALUES (?,?)", nid, cid)
            made += 1
        return made

    @app.get("/api/estates/{eid}/decisions")
    def list_decisions(eid: str):
        """Every decision the owner has recorded on this estate, newest first: pattern statuses, action and proposal states,
        connections confirmed or retired, Size rows kept or done. Each carries the reason, who and when, and names its object."""
        from .orac.bridge import Bridge
        w = workspace(eid)
        names = Bridge(db, eid)._model_names()
        cards = {c["key"]: c for c in (_plan_sel(w).get("candidates") or [])}
        props = {p["id"]: p for p in planmod.list_proposals(db, eid, withdrawn=True)}
        out = []
        for r in db.q("SELECT finding_key AS key, state, reason, author_id AS by, snapshot_id, updated FROM finding_state WHERE estate_id=? ORDER BY updated DESC", eid):
            k = r["key"]
            d = {"key": k, "state": r["state"], "reason": r["reason"] or "", "by": r["by"], "updated": r["updated"], "snapshot_id": r["snapshot_id"]}
            if fstate.is_edge_key(k):
                fid, _, tid = k[len(fstate.EDGE_PREFIX):].partition("|")
                d.update(kind="connection", label=f"{names.get(fid, fid)} -> {names.get(tid, tid)}", model=names.get(fid), to=names.get(tid),
                         object={"kind": "model", "model": names.get(fid), "ref": names.get(fid)})
            elif fstate.is_size_key(k):
                model, _, ref = k[len(fstate.SIZE_PREFIX):].partition("::")
                d.update(kind="size", label=ref, model=model, object={"kind": "line_item", "model": model, "ref": ref})
            elif k.startswith("action:"):
                c = cards.get(k[7:])
                d.update(kind="action", label=c["title"] if c else k[7:], model=c["model"] if c else None, object=None)
            elif k.startswith("proposal:"):
                p = props.get(k[9:])
                d.update(kind="proposal", label=p["title"] if p else k[9:], model=(p or {}).get("model"), object=None)
            else:
                parts = k.split("::")
                d.update(kind="pattern", label=parts[2] if len(parts) > 2 else k, model=parts[0] if len(parts) > 2 else None, rule=parts[1] if len(parts) > 2 else None,
                         object={"kind": "pattern", "model": parts[0] if len(parts) > 2 else None, "ref": k})
            out.append(d)
        return out

    @app.post("/api/estates/{eid}/notes")
    def create_note(request: Request, eid: str, body: dict):
        estate(eid)
        try:
            n = notesmod.create(db, eid, body.get("body", ""), title=body.get("title", ""), type=body.get("type") or "conclusion",
                                status=body.get("status") or "working_assumption", objects=body.get("objects") or body.get("scopes") or None,
                                author=who(request), origin_kind=body.get("origin_kind") or "user", origin_conversation_id=body.get("conversation_id"),
                                origin_turn_id=body.get("turn_id"), sources=body.get("sources") or ())
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        _cite_scopes(eid, n["id"])
        n = notesmod.get(db, n["id"])
        forget_state(eid)
        return n

    @app.get("/api/notes/{nid}")
    def get_note(nid: str):
        try:
            return notesmod.get(db, nid)
        except KeyError:
            raise HTTPException(404, "no such note")

    @app.patch("/api/notes/{nid}")
    def patch_note(request: Request, nid: str, body: dict):
        try:
            before = notesmod.get(db, nid)
            n = notesmod.update(db, nid, title=body.get("title"), body=body.get("body"), type=body.get("type"), status=body.get("status"),
                                objects=body.get("objects") if "objects" in body else None, by=who(request), reviewed_on=active_sid(before["estate_id"]))
        except KeyError:
            raise HTTPException(404, "no such note")
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        if "objects" in body:
            _cite_scopes(n["estate_id"], nid)
            n = notesmod.get(db, nid)
        forget_state(n["estate_id"])
        return n

    @app.post("/api/notes/{nid}/reviewed")
    def note_reviewed(request: Request, nid: str):
        """The owner has looked at what moved under a flagged note and keeps it: the flag clears and the snapshot reviewed
        against becomes the baseline for the next activation."""
        try:
            n = notesmod.mark_reviewed(db, nid, by=who(request))
        except KeyError:
            raise HTTPException(404, "no such note")
        forget_state(n["estate_id"])
        return n

    @app.post("/api/notes/{nid}/supersede")
    def supersede_note(request: Request, nid: str, body: dict | None = None):
        try:
            n = notesmod.supersede(db, nid, by_note=(body or {}).get("by_note"), by=who(request))
        except KeyError:
            raise HTTPException(404, "no such note")
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        forget_state(n["estate_id"])
        return n

    @app.delete("/api/notes/{nid}")
    def delete_note(request: Request, nid: str):
        try:
            n = notesmod.get(db, nid)
            notesmod.delete(db, nid, by=who(request))
        except KeyError:
            raise HTTPException(404, "no such note")
        forget_state(n["estate_id"])
        return {"deleted": nid}

    def forget_state(eid: str) -> None:
        """Notes or finding state changed: every workspace over this estate re-reads them, and the material every live
        session caches follows the workspace version."""
        for k, w in app.state.workspaces.items():
            if k[0] == eid:
                w.reload()

    def forget_handles(eid: str) -> None:
        """A proposal came or went: the decision handles the validator knows are recomputed on the next answer."""
        for k, w in app.state.workspaces.items():
            if k[0] == eid:
                w.__dict__.pop("_handles", None)

    # ---------- finding state ----------
    @app.get("/api/estates/{eid}/findings")
    def get_findings(eid: str):
        estate(eid)
        return fstate.as_statuses(db, eid)

    @app.patch("/api/estates/{eid}/findings")
    def set_finding(request: Request, eid: str, body: dict):
        estate(eid)
        try:
            r = fstate.set_state(db, eid, body.get("key", ""), body.get("state", ""), body.get("reason", ""), by=who(request),
                                 snapshot_id=active_sid(eid))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        forget_state(eid)
        return r

    @app.put("/api/estates/{eid}/edges")
    def set_edge(request: Request, eid: str, body: dict):
        """The owner's word on a feed between two models: confirmed (real and used), retired (the import survives, the feed is
        dead) or inferred (back to what the import names say). Only a feed the import names show can be marked."""
        w = workspace(eid)
        f, t = (body.get("from") or "").strip(), (body.get("to") or "").strip()
        edge = next((e for e in w.estate.edges if e["from"].lower() == f.lower() and e["to"].lower() == t.lower()), None)
        if edge is None:
            raise HTTPException(404, "the exports show no import between those models")
        try:
            rec = w.set_edge_state(edge["from"], edge["to"], body.get("state") or "inferred", body.get("reason") or "", by=who(request) or "user")
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        forget_state(eid)
        return dict(edge, state=rec)

    @app.post("/api/conversations/{cid}/messages")
    def post_message(request: Request, cid: str, body: dict):
        text = (body.get("text") or "").strip()
        _question(text)
        _cap(request)
        return _turn(cid, text, who(request), _mode(request, body))

    def _prefs(request: Request) -> dict:
        """A login's preferences; on a server with no accounts, the one set for the machine."""
        u = getattr(request.state, "user", None)
        if u:
            row = db.one("SELECT prefs_json FROM users WHERE id=?", u["id"])
            raw = row["prefs_json"] if row else None
        else:
            row = db.one("SELECT value FROM settings WHERE workspace_id=? AND key='prefs'", ws_id)
            raw = row["value"] if row else None
        try:
            p = json.loads(raw) if raw else {}
        except ValueError:
            p = {}
        out = {"answer_mode": p.get("answer_mode") if p.get("answer_mode") in ("full", "concise") else "full"}
        if p.get("trace_level") in TRACE_LEVELS:          # only when this login chose one: with the time it did
            out |= {"trace_level": p["trace_level"], "trace_level_at": p.get("trace_level_at")}
        return out

    def _prefs_of(uid: str | None) -> dict:
        if uid:
            row = db.one("SELECT prefs_json FROM users WHERE id=?", uid); raw = row["prefs_json"] if row else None
        else:
            row = db.one("SELECT value FROM settings WHERE workspace_id=? AND key='prefs'", ws_id); raw = row["value"] if row else None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def _trace(user: dict | None) -> dict:
        """What this login's turns send to the outside tracer, and why. Decided per login: an admin's own turns go with
        content when a key is set; anyone else's go nowhere until that login turns it on for itself. With no logins at
        all the one person at the keyboard is the one who set the key. The instance's ceiling applies on top."""
        t = app.state.tracer
        ceiling = getattr(t, "ceiling", "content")
        p = _prefs_of(user["id"] if user else None)
        chosen = p.get("trace_level") if p.get("trace_level") in TRACE_LEVELS else None
        default = "off" if not t.enabled else ("content" if (user is None or user.get("role") == "owner") else "off")
        level = chosen or default
        if not t.enabled:
            level = "off"
        elif level == "content" and ceiling == "structure":
            level = "structure"
        return {"available": bool(t.enabled), "level": level, "chosen": chosen, "chosen_at": p.get("trace_level_at") if chosen else None, "default": default, "ceiling": ceiling}

    def _trace_level_of(uid: str | None) -> str:
        return _trace(db.one("SELECT * FROM users WHERE id=?", uid) if uid else None)["level"]

    def _mode(request: Request, body: dict) -> str:
        m = (body or {}).get("mode")
        return m if m in ("full", "concise") else _prefs(request)["answer_mode"]

    @app.get("/api/prefs")
    def get_prefs(request: Request):
        return _prefs(request)

    @app.put("/api/prefs")
    def put_prefs(request: Request, body: dict):
        p = _prefs(request)
        if body.get("answer_mode") in ("full", "concise"):
            p["answer_mode"] = body["answer_mode"]
        if "trace_level" in body:                         # a login's own choice, for its own turns only: there is no way to name another login here
            if body["trace_level"] not in TRACE_LEVELS:
                raise HTTPException(400, f"trace_level must be one of {', '.join(TRACE_LEVELS)}")
            if not app.state.tracer.enabled:
                raise HTTPException(400, "tracing is not set up on this instance: there is nothing to turn on")
            p["trace_level"] = body["trace_level"]; p["trace_level_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        u = getattr(request.state, "user", None)
        if u:
            db.run("UPDATE users SET prefs_json=? WHERE id=?", json.dumps(p), u["id"])
        else:
            db.run("INSERT OR REPLACE INTO settings(workspace_id, key, value) VALUES (?,?,?)", ws_id, "prefs", json.dumps(p))
        return p

    BUSY = "the architect is still answering in this conversation; wait for that answer before asking again"

    def _question(text: str) -> None:
        """A question is a question: not empty, and not long enough to be a way of spending someone's budget in one go."""
        if not (text or "").strip():
            raise HTTPException(400, "empty message")
        if len(text) > MAX_QUESTION_CHARS:
            raise HTTPException(400, f"a question may be up to {MAX_QUESTION_CHARS:,} characters; this one is {len(text):,}. Put long material in a document and ask about it")

    def _cap(request: Request) -> None:
        """A login over its spend cap is told so before the model is called."""
        over = auth.over_cap(db, getattr(request.state, "user", None))
        if over:
            raise HTTPException(402, {"message": f"This login has reached its spend cap: ${over['spent_usd']:.2f} used of ${over['cap_usd']:.2f}. Ask the person who gave you "
                                                 "the login to raise it.", "cap": over})

    def _turn(cid: str, text: str, user: str | None = None, mode: str = "full") -> dict:
        sess = session_of(cid, user)
        if not sess.lock.acquire(blocking=False):
            raise HTTPException(409, BUSY)
        try:
            sess.trace_level = _trace_level_of(user)      # read now, for this turn: a change in Settings applies from the next question
            sess.ask(text, mode)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(502, f"the model call failed: {e}")
        finally:
            sess.lock.release()
        return sess.turns[-1]

    @app.post("/api/conversations/{cid}/stream")
    def stream_message(request: Request, cid: str, body: dict):
        """Server-sent events: one `data:` line per event from Session.ask_stream."""
        text = (body.get("text") or "").strip()
        _question(text)
        _cap(request)
        sess = session_of(cid, who(request))
        mode = _mode(request, body)
        if not sess.lock.acquire(blocking=False):
            raise HTTPException(409, BUSY)

        level = _trace_level_of(who(request))

        def gen():
            try:
                sess.trace_level = level
                for ev in sess.ask_stream(text, mode):
                    if ev["type"] == "tool" and ev.get("args") is None:
                        continue                      # the start event; the full one follows with args
                    yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
            except Exception as e:
                yield "data: " + json.dumps({"type": "error", "message": f"the model call failed: {e}"}) + "\n\n"
            finally:
                sess.lock.release()                   # whichever thread finishes the stream, or closes it early
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"cache-control": "no-cache", "x-accel-buffering": "no"})


    # ---------- the demo state (v0.2 P4) ----------
    def demo_reset(by: str | None = None) -> dict:
        """Write the demo workspaces from the files shipped with the package, replacing any earlier copy of them.
        Deterministic: the same models, snapshot contents, notes, feed state, documents (ids and sections) every time."""
        man = demomod.manifest()
        base = Path(man["root"])
        out = []
        for ws in man["workspaces"]:
            eid = demomod.estate_id(ws["id"], by)            # each login has its own copy: a workspace is never shared by default
            if reg.get_estate(db, eid):
                _discard_estate(eid)
            e = reg.create_estate(db, ws_id, ws["name"], created_by=by, estate_id=eid)
            if by:
                access.add_member(db, eid, by)
            snap = snaps.create(eid, label=ws.get("label") or "demo exports", inherit=False, created_by=by)
            for name, kind, body, fname in demomod.files_of(ws):
                m = reg.find_model(db, eid, name) or reg.add_model(db, eid, name, created_by=by)
                snaps.stage(snap["id"], m["id"], kind, body, fname)
            why = snaps.ready(snap["id"])
            if why:
                raise HTTPException(500, "the demo exports are not complete: " + "; ".join(why))
            run = snaps.process(snap["id"])
            if run["status"] != "ok":
                raise HTTPException(500, "the demo exports did not parse: " + str(run.get("error")))
            snaps.activate(snap["id"], by=by)
            if ws.get("notes"):
                for n in json.loads((base / ws["notes"]).read_text(encoding="utf-8")):
                    note = notesmod.create(db, eid, n["body"], title=n.get("title") or "", type=n.get("type") or "conclusion", status=n.get("status") or "working_assumption",
                                           objects=n.get("scopes") or None, author=by, origin_kind="import")
                    _cite_scopes(eid, note["id"])
            bridge = Bridge(db, eid, snap["id"], user=by)
            for ed in ws.get("edges") or []:
                bridge.set_edge_state(ed["from"], ed["to"], ed["state"], ed.get("reason") or "", by="demo")
            er = run_of(snap["id"])
            for doc in ws.get("documents") or []:
                p = base / doc["file"]
                docsmod.add(db, eid, p.name, p.read_bytes(), estate_run=er, by=by, doc_id=demomod.doc_id(eid, p.name), summary_text=doc.get("summary"))
            forget(eid); forget_sessions(eid)
            workspace(eid)                               # read once now: the line-item index is written
            out.append({"id": eid, "key": ws["id"], "name": e["name"], "models": len(ws["models"]), "documents": len(ws.get("documents") or []), "snapshot": snap["id"]})
            db.audit(ws_id, "demo.reset", eid, {"models": len(ws["models"])}, by)
        return {"workspaces": out, "questions": man.get("questions") or []}
    app.state.demo_reset = demo_reset
    # ARCHITECT_DEMO=1: the demo workspaces are written on first start, for the admin just created or, on an open
    # instance with no workspaces yet, for the machine.
    if os.environ.get("ARCHITECT_DEMO", "").strip() == "1" and demomod.root() is not None:
        try:
            if app.state.bootstrap is not None:
                demo_reset(app.state.bootstrap["id"])
            elif auth.no_accounts(db) and not reg.list_estates(db, ws_id, include_archived=True):
                demo_reset(None)
        except Exception as ex:
            print(f"the demo workspaces could not be written: {type(ex).__name__}: {ex}")

    @app.get("/api/demo")
    def demo_info(request: Request):
        """Whether the demo files are installed, which demo workspaces this login has, and the scripted questions."""
        by = who(request)
        try:
            man = demomod.manifest()
        except FileNotFoundError as ex:
            return {"available": False, "why": str(ex), "workspaces": [], "questions": []}
        return {"available": True, "about": man.get("about"), "questions": man.get("questions") or [],
                "workspaces": [{"key": w["id"], "id": demomod.estate_id(w["id"], by), "name": w["name"], "present": bool(reg.get_estate(db, demomod.estate_id(w["id"], by)))}
                               for w in man["workspaces"]]}

    @app.post("/api/demo/reset")
    def demo_reset_route(request: Request):
        """Replace this login's demo workspaces with a fresh copy (on a server with no accounts, the machine's)."""
        try:
            return demo_reset(who(request))
        except FileNotFoundError as ex:
            raise HTTPException(404, str(ex))

    # ---------- the line-item index (v0.2 P2) ----------
    @app.get("/api/estates/{eid}/lineitems")
    def line_items(eid: str, model: str | None = None, module: str | None = None, function: str | None = None, references: str | None = None,
                   referenced_by: str | None = None, dimension: str | None = None, format: str | None = None, text: str | None = None,
                   calculated: bool | None = None, unreferenced: bool | None = None, min_cells: int | None = None, group_by: str | None = None,
                   sort: str = "cells", limit: int = 10):
        """The same question the chat tool asks of the index: an exact count, a breakdown and the first rows."""
        wk = workspace(eid)
        lindex.ensure(db, wk.snapshot_id, wk.estate)          # checked on every read: a workspace kept in memory outlives a dropped index
        r = lindex.query(db, wk.snapshot_id, model=model, module=module, function=function, references=references, referenced_by=referenced_by, dimension=dimension,
                         format=format, text=text, calculated=calculated, unreferenced=unreferenced, min_cells=min_cells, group_by=group_by, sort=sort, limit=limit)
        if "error" in r:
            raise HTTPException(400, r["error"])
        return r

    @app.get("/api/estates/{eid}/profile")
    def estate_profile(eid: str, model: str):
        """What the dashboard draws inside a model, read off the index and the modules export: who reads whom (module by
        module, the number of line items of one that read the other), the functions the formulas use, and each module's
        functional area as exported (blank when the Modules export has none)."""
        wk = workspace(eid)
        m = next((x for x in wk.estate.models if x.name == model), None)
        if m is None:
            raise HTTPException(404, "no such model")
        sid = wk.snapshot_id
        lindex.ensure(db, sid, wk.estate)
        edges = db.q("SELECT i.module AS f, r.to_module AS t, COUNT(DISTINCT r.from_ref) AS n FROM li_refs r JOIN li_index i ON i.snapshot_id=r.snapshot_id AND i.model=r.model "
                     "AND i.ref=r.from_ref WHERE r.snapshot_id=? AND r.model=? AND i.module<>r.to_module GROUP BY i.module, r.to_module", sid, model)
        funcs = db.q("SELECT f.fn, f.kind, COUNT(*) AS n, COALESCE(SUM(i.cells),0) AS cells FROM li_funcs f JOIN li_index i ON i.snapshot_id=f.snapshot_id AND i.model=f.model AND i.ref=f.ref "
                     "WHERE f.snapshot_id=? AND f.model=? GROUP BY f.fn, f.kind ORDER BY n DESC, f.fn LIMIT 12", sid, model)
        for f in funcs:
            top = db.one("SELECT i.module, COUNT(*) AS n FROM li_funcs f JOIN li_index i ON i.snapshot_id=f.snapshot_id AND i.model=f.model AND i.ref=f.ref "
                         "WHERE f.snapshot_id=? AND f.model=? AND f.fn=? AND f.kind=? GROUP BY i.module ORDER BY n DESC, i.module LIMIT 1", sid, model, f["fn"], f["kind"])
            f["most_in"] = top["module"] if top else None
        longest = db.q("SELECT ref, formula_len, ifs, depth, cells FROM li_index WHERE snapshot_id=? AND model=? AND calculated=1 ORDER BY formula_len DESC LIMIT 5", sid, model)
        return {"model": model, "modules": [{"name": n, "area": mod.functional_area or "", "line_items": len(mod.line_items)} for n, mod in sorted(m.model.modules.items())],
                "has_areas": any(mod.functional_area for mod in m.model.modules.values()), "edges": [[e["f"], e["t"], e["n"]] for e in edges], "functions": funcs,
                "longest": longest, "stats": lindex.stats(db, sid)}

    # ---------- project documents (v0.2 P1) ----------
    def _summariser(uid: str | None = None):
        """Writes a card's summary once, at upload, when the server has a model; None otherwise (the opening sentences stand in).
        It is a model call like any other: refused when the login is over its spend cap (the opening sentences stand in
        then too) and put on the login's ledger."""
        if not app.state.summaries:
            return None
        def summarise(title: str, text: str) -> str:
            from .chat import SpendCapReached, _usage_of
            try:
                _spend_gate(uid)
            except SpendCapReached:
                return ""
            kw = _client_kw()
            client = kw.get("client")
            if client is None:
                import anthropic
                client = anthropic.Anthropic(api_key=kw["api_key"])
            call = dict(model=app.state.model_id, max_tokens=220,
                        system="You write the card of a project document for an index. Reply with two sentences, at most 45 words, plain text: what the "
                               "document is and which decisions or facts it holds. No preamble, no quotation marks.",
                        messages=[{"role": "user", "content": "Title: " + title + "\n\n" + text}])
            from .chat import cost_usd
            level = _trace_level_of(uid)                  # the uploader's own: off sends nothing, structure sends sizes, content sends the text
            tracer = app.state.tracer if level != "off" and hasattr(app.state.tracer, "client") else telemetry.Tracer(None)
            with tracer.turn("document summary", user_id=uid, metadata={"model": app.state.model_id, "kind": "summary"}, input={"title": title, "text": text},
                             level=level, fixed_name=True) as tr:
                with tr.generation("model", app.state.model_id, input={"system": call["system"], "messages": call["messages"]}) as g:
                    if hasattr(client.messages, "stream"):            # the Codex route only streams
                        with client.messages.stream(**call) as st:
                            for _ in st:
                                pass
                            r = st.get_final_message()
                    else:
                        r = client.messages.create(**call)
                    u = _usage_of(r)
                    out_text = "".join(getattr(b, "text", "") for b in r.content if getattr(b, "type", "") == "text").strip()
                    g.update(output=out_text, usage=u, cost_usd=cost_usd(u, app.state.model_id) if u else None)
                tr.output(out_text)
            if u:
                _spent(uid, u, kind="summary")
            return out_text
        return summarise

    def _docs_payload(eid: str) -> dict:
        return {"documents": docsmod.list_documents(db, eid), "totals": docsmod.totals(db, eid),
                "limits": {"documents": docsmod.MAX_DOCS, "bytes": docsmod.MAX_BYTES,
                           "note": f"Up to {docsmod.MAX_DOCS} project documents, {docsmod.MAX_BYTES // (1024 * 1024)} MB each: project documents, not an archive. "
                                   "PDF, Word (.docx), Markdown, text, CSV or a script. A scanned PDF is not read: there is no OCR."}}

    @app.get("/api/estates/{eid}/documents")
    def list_documents(eid: str):
        estate(eid)
        return _docs_payload(eid)

    @app.post("/api/estates/{eid}/documents")
    def upload_documents(request: Request, eid: str, files: list[UploadFile] = File(default=[]), replaces: str = Form(default="")):
        """One or more documents into the workspace; with `replaces`, one file as the new version of that document.
        Each file answers for itself: read and split, or the reason it was not taken.
        A plain function on purpose: reading a PDF and having the model write the card's summary take seconds, and a
        plain route runs in a worker thread, so other requests are answered meanwhile."""
        estate(eid)
        act = active_sid(eid)
        er = run_of(act) if act else None
        summarise = _summariser(who(request))
        out = []
        for up in files:
            if not up or not up.filename:
                continue
            if (up.size or 0) > docsmod.MAX_BYTES:        # said by the upload itself: refused before it is read into memory
                out.append({"ok": False, "filename": up.filename, "error": f"{up.filename} is {up.size / 1e6:.1f} MB: a document may be up to {docsmod.MAX_BYTES // (1024 * 1024)} MB"})
                continue
            body = up.file.read(docsmod.MAX_BYTES + 1)
            try:
                d = docsmod.add(db, eid, up.filename, body, estate_run=er, by=who(request), summarise=summarise, replaces=replaces or None)
                e = estate(eid)
                db.audit(e["workspace_id"], "document.replace" if replaces else "document.add", d["id"], {"filename": up.filename, "bytes": len(body), "sections": len(d["sections"])}, who(request))
                out.append({"ok": True, "filename": up.filename, "document": d})
            except ValueError as ex:
                out.append({"ok": False, "filename": up.filename, "error": str(ex)})
        if not out:
            raise HTTPException(400, "no file was sent")
        forget_sessions(eid)                 # live conversations read the cards again
        return _docs_payload(eid) | {"results": out}

    @app.get("/api/documents/{did}")
    def get_document(did: str):
        try:
            d = docsmod.get(db, did)
        except KeyError:
            raise HTTPException(404, "no such document")
        d["sections"] = [dict(s, text=db.one("SELECT text FROM doc_sections WHERE id=?", s["id"])["text"]) for s in d["sections"]]
        return d

    @app.delete("/api/documents/{did}")
    def delete_document(request: Request, did: str):
        r = docsmod.remove(db, did)
        if not r:
            raise HTTPException(404, "no such document")
        e = estate(r["estate_id"])
        db.audit(e["workspace_id"], "document.remove", did, {"filename": r["filename"]}, who(request))
        forget_sessions(r["estate_id"])
        return _docs_payload(r["estate_id"]) | {"removed": did}

    @app.get("/api/estates/{eid}/documents/search")
    def search_documents(eid: str, q: str = "", objects: str = "", limit: int = 8):
        estate(eid)
        return docsmod.search(db, eid, q, [o for o in objects.split(",") if o.strip()], None, limit)

    # ---------- citations: what an id opens ----------
    def _snapshot_head(sid: str | None) -> dict | None:
        return db.one("SELECT id, estate_id, label, status, created, activated_at, superseded_at FROM snapshots WHERE id=?", sid) if sid else None

    def _status_of(eid: str):
        """The whole record, so the drawer can show the reason, who and when beside the status."""
        st = fstate.as_statuses(db, eid)
        return lambda pid: st.get(pid) or {"status": "open"}

    def _plan_mentions(eid: str, sid: str, model: str, ref: str, kind: str) -> list[dict]:
        """The action-plan cards and proposals that name this object, each with the owner's decision on it."""
        try:
            sel = _plan_sel(workspace(eid, sid))
        except HTTPException:
            return []
        states = fstate.action_states(db, eid)
        on_plan = {c["key"] for c in sel.get("actions") or []}
        out = []
        for c in sel.get("candidates") or []:
            if c.get("model") != model:
                continue
            objs = c.get("objects") or []
            hit = ref in objs or (kind == "module" and any(o.split(".", 1)[0] == ref for o in objs))      # a card names line items; a module is hit through them
            if hit:
                st = states.get("action:" + c["key"])
                out.append({"key": "action:" + c["key"], "title": c.get("title"), "kind": c.get("kind"), "worth": c.get("worth"), "on_plan": c["key"] in on_plan, "proposal": False,
                            "state": st or {"state": "to_review", "reason": "", "by": None, "updated": None, "default": True}})
        for p in planmod.list_proposals(db, eid):
            if (p.get("model") or "") == model and ref in (p.get("objects") or []):
                out.append({"key": "proposal:" + p["id"], "title": p["title"], "kind": "proposal", "worth": None, "proposal": True,
                            "state": states.get("proposal:" + p["id"])})
        return out[:12]

    def _edge_state_of(eid: str):
        from .orac.bridge import Bridge
        st = Bridge(db, eid).edge_states_by_name()
        return lambda f, t: st.get((f, t))

    def _evidence(eid: str, sid: str | None, kind: str, model: str | None, ref: str, name: str | None = None, provenance: str = "observed",
                  tool: str = "", cid: str | None = None, looked_up: bool = False) -> dict:
        """The payload behind a citation: the object as the snapshot held it, the export row it was read from, whether
        that snapshot is still the one the estate reads (and what the object is now if not), and where else it is cited."""
        act = db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)
        head = _snapshot_head(sid)
        fallback = False
        if head is None or head["estate_id"] != eid:
            if not act:
                raise HTTPException(409, "this estate has no active snapshot")
            fallback = sid is not None
            sid = act["id"]; head = _snapshot_head(sid)
        cid = cid or cite_id(sid, kind, model or "", ref)
        out = {"id": cid, "kind": kind, "model": model, "ref": ref, "name": name or ref, "provenance": provenance, "tool": tool, "estate": eid,
               "snapshot": head, "current": bool(act and act["id"] == sid), "snapshot_fallback": fallback, "looked_up_now": looked_up,
               "export_row": None, "now": None}
        if kind == "note":
            try:
                note = notesmod.get(db, ref)
            except KeyError:
                raise HTTPException(404, "that note no longer exists")
            if note["estate_id"] != eid:
                raise HTTPException(404, "that note belongs to another estate")
            out["object"] = note; out["provenance"] = note_provenance(note); out["name"] = note["title"] or ref
        elif kind == "document":
            sec = docsmod.get_section(db, ref, eid)
            if sec is None:
                raise HTTPException(404, "that document section is no longer in the workspace (the document was replaced or removed)")
            rows = db.q("SELECT payload_json FROM citations WHERE id=? AND owner_kind='turn'", cid)
            quotes = []
            for r in rows:
                for q in (json.loads(r["payload_json"] or "{}") or {}).get("quotes") or []:
                    if q.get("quote") and q["quote"] not in [x["quote"] for x in quotes]:
                        quotes.append(q)
            out["object"] = {"kind": "document", "ref": ref, "name": f"{sec['doc_title']} · {sec['heading']}" if sec["heading"] else sec["doc_title"],
                             "document": {"id": sec["doc_id"], "title": sec["doc_title"], "type": sec["doc_type"], "date": sec["doc_date"], "filename": sec["filename"]},
                             "heading": sec["heading"], "position": [sec["seq"] + 1, sec["of"]], "text": sec["text"], "tokens": sec["tokens"],
                             "names": sec["objects"], "quotes": quotes}
            out["name"] = out["object"]["name"]
        else:
            er = run_of(sid)
            obj = objmod.resolve(er, kind, model, ref, sid, status_of=_status_of(eid), edge_state_of=_edge_state_of(eid))
            if obj is None:
                raise HTTPException(404, f"snapshot {sid} holds no {kind.replace('_', ' ')} named {ref!r}")
            out["object"] = obj; out["name"] = name or obj.get("name") or ref; out["model"] = obj.get("model") or model
            if kind == "line_item" and obj.get("model"):
                axes = _dims_item(eid, sid, obj["model"], obj["ref"])                      # applied versus required axes (backlog 18)
                if axes is not None:
                    axes["key"] = fstate.size_key(obj["model"], obj["ref"])
                    axes["decision"] = fstate.size_states(db, eid).get(axes["key"])     # the owner's word on the Size row, if any
                out["object"]["axes"] = axes
            if kind in ("line_item", "module") and obj.get("model"):
                out["object"]["plan"] = _plan_mentions(eid, sid, obj["model"], obj["ref"], kind)
            row_kind = objmod.ROW_KIND.get(kind)
            if row_kind and obj.get("model"):
                key = (obj["module"], obj["name"]) if kind == "line_item" else obj["ref"]
                out["export_row"] = objmod.export_row(snaps, sid, obj["model"], row_kind, key)
            if act and act["id"] != sid:
                now = objmod.resolve(run_of(act["id"]), kind, obj.get("model") or model, obj["ref"], act["id"], status_of=_status_of(eid), edge_state_of=_edge_state_of(eid))
                out["now"] = {"snapshot_id": act["id"], "found": now is not None, "id": now["id"] if now else None,
                              "formula": now.get("formula") if now else None,
                              "changed": bool(now and kind == "line_item" and now.get("formula") != obj.get("formula"))}
        out["cited_in"] = {"turns": db.q("SELECT t.id AS turn_id, t.seq, t.conversation_id, c.title, t.created FROM citations x JOIN turns t ON t.id=x.owner_id "
                                         "JOIN conversations c ON c.id=t.conversation_id WHERE x.id=? AND x.owner_kind='turn' ORDER BY t.created DESC LIMIT 20", cid),
                           "notes": db.q("SELECT n.id, n.title, n.status, n.type FROM note_sources s JOIN notes n ON n.id=s.note_id WHERE s.citation_id=? "
                                         "ORDER BY n.updated DESC LIMIT 20", cid)}
        return out

    @app.get("/api/citations/{cid}")
    def get_citation(cid: str):
        """What a citation id opens. The id must be one the tools handed: recorded on a turn or a note, or held by a live session."""
        row = db.one("SELECT * FROM citations WHERE id=? ORDER BY CASE owner_kind WHEN 'turn' THEN 0 ELSE 1 END LIMIT 1", cid)
        if row:
            kind, model, ref, sid, prov, tool = row["kind"], row["model_id"], row["object_ref"], row["snapshot_id"], row["provenance"], row["source_ref"] or ""
            name = (json.loads(row["payload_json"] or "{}") or {}).get("name")
            head = _snapshot_head(sid)
            if row["owner_kind"] == "turn":
                r = db.one("SELECT c.estate_id FROM turns t JOIN conversations c ON c.id=t.conversation_id WHERE t.id=?", row["owner_id"])
            else:
                r = db.one("SELECT estate_id FROM notes WHERE id=?", row["owner_id"])
            eid = r["estate_id"] if r else None          # the workspace of the answer or note that carries the citation: the one the guard checked
            if head and head["estate_id"] != eid:        # a citation onto a snapshot of another workspace opens nothing
                raise HTTPException(404, "no such citation")
        else:
            eid = None
            for s in list(app.state.sessions.values()):
                live = s.ev.resolve(cid)
                if live is not None:
                    kind, model, ref, sid, prov, tool, name, eid = live.kind, live.model, live.ref, live.snapshot_id, live.provenance, live.tool, live.name, s.w.estate_id
                    break
            if eid is None:
                raise HTTPException(404, "no citation with that id: the tools never handed it")
        if not eid or not reg.get_estate(db, eid):
            raise HTTPException(404, "the estate this citation belongs to no longer exists")
        return _evidence(eid, sid, kind, model or None, ref, name, prov, tool, cid=cid)

    @app.get("/api/estates/{eid}/object")
    def lookup_object(eid: str, ref: str, model: str | None = None, kind: str | None = None, snapshot: str | None = None):
        """What a name opens when it was never handed as a citation: looked up now over the active snapshot (or the one given)."""
        estate(eid)
        ref = (ref or "").strip()
        if not ref:
            raise HTTPException(400, "which object?")
        if kind == "note" or NOTE_ID.fullmatch(ref):
            return _evidence(eid, snapshot, "note", None, ref, looked_up=True)
        if kind == "document" or SECTION_ID.fullmatch(ref):
            return _evidence(eid, snapshot, "document", None, ref, looked_up=True)
        head = _snapshot_head(snapshot)
        sid = head["id"] if head and head["estate_id"] == eid else (db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid) or {}).get("id")
        if not sid:
            raise HTTPException(409, "this estate has no active snapshot")
        er = run_of(sid)
        k, mdl, canon = objmod.guess(er, ref, model, kind)
        if not k:
            raise HTTPException(404, f"nothing in the estate is named {ref!r}")
        return _evidence(eid, sid, k, mdl, canon, looked_up=True)

    # ---------- stage 4: the dependency explorer and the action plan ----------
    app.state.plans = {}          # snapshot id -> the deterministic selection (the parse does not change under a snapshot)

    def _plan_sel(w: Workspace) -> dict:
        sel = app.state.plans.get(w.snapshot_id)
        if sel is None:
            sel = planmod.deterministic(w.estate)
            app.state.plans[w.snapshot_id] = sel
        return sel

    @app.get("/api/estates/{eid}/deps/search")
    def deps_search(eid: str, q: str = "", model: str | None = None, kind: str | None = None, limit: int = 50):
        """Line items and modules by name, module or formula text; the hubs when nothing is typed. Every row carries a citation id."""
        w = workspace(eid)
        return depsmod.search(w.estate, q, model=model or None, kind=kind or None, limit=max(1, min(limit, 500)), snapshot_id=w.snapshot_id)

    @app.get("/api/estates/{eid}/deps/reach")
    def deps_reach(eid: str, ref: str, model: str, direction: str = "downstream", depth: int | None = None, limit: int = 400):
        """The reach of a change: unique line items, modules and models over the estate's closure, actions at module level, feeds as inferred."""
        w = workspace(eid)
        r = depsmod.reach(w.estate, model, ref, direction, depth, snapshot_id=w.snapshot_id, limit=max(1, min(limit, 5000)))
        if "error" in r:
            raise HTTPException(404, r["error"])
        return r

    @app.get("/api/estates/{eid}/deps/graph")
    def deps_graph(eid: str, ref: str, model: str, actions: bool = True, feeds: bool = True):
        """One node and its direct neighbours, in the shape the graph grows from on each click."""
        w = workspace(eid)
        r = depsmod.graph(w.estate, model, ref, snapshot_id=w.snapshot_id, actions=actions, feeds=feeds)
        if "error" in r:
            raise HTTPException(404, r["error"])
        return r

    @app.get("/api/estates/{eid}/plan")
    def get_plan(eid: str):
        """The action plan: deterministic cards with the owner's state, and the proposals kept beside them."""
        w = workspace(eid)
        return planmod.assemble(db, eid, w.estate, w.snapshot_id, _plan_sel(w))

    @app.get("/api/estates/{eid}/tests")
    def get_tests(eid: str):
        """Every test of the catalogue with its result on the active snapshot, and the rollup by area. A rule behind a test
        carries a citation id, so it opens in the drawer."""
        w = workspace(eid)
        rows = checksmod.of(w)
        cite = planmod._citer(w.snapshot_id)
        return dict(checksmod.rollup(rows), snapshot=w.snapshot_id, note=checksmod.NOTE,
                    tests=[dict(r, rules=[{"ref": x, "id": cite("finding", "", x)} for x in r["rules"]]) for r in rows])

    @app.put("/api/estates/{eid}/plan/state")
    def set_plan_state(request: Request, eid: str, body: dict):
        """Record a decision on an action (key action:<candidate key> or proposal:<id>). It verifies nothing in Anaplan."""
        w = workspace(eid)
        key = (body.get("key") or "").strip()
        if key not in planmod.valid_keys(db, eid, _plan_sel(w)):
            raise HTTPException(404, "no such action on the plan")
        try:
            return fstate.set_action_state(db, eid, key, body.get("state") or "", body.get("reason") or "", by=who(request), snapshot_id=w.snapshot_id)
        except ValueError as ex:
            raise HTTPException(400, str(ex))

    @app.post("/api/estates/{eid}/plan/proposals")
    def add_proposal(request: Request, eid: str, body: dict):
        """An action the owner adds by hand: kept with the proposals, origin user, no state until one is recorded."""
        w = workspace(eid)
        model = (body.get("model") or "").strip()
        objects = body.get("objects") or []
        if isinstance(objects, str):
            objects = [o.strip() for o in objects.split(",") if o.strip()]
        try:
            canon = planmod.check_objects(w.estate, model, objects) if (model or objects) else []
            steps = body.get("steps") or []
            if isinstance(steps, str):
                steps = steps.splitlines()
            p = planmod.propose(db, eid, body.get("title") or "", body.get("why") or "", steps, body.get("done_when") or "",
                                objmod.find_model(w.estate, model).name if model and objmod.find_model(w.estate, model) else model, canon,
                                origin="user", by=who(request), snapshot_id=w.snapshot_id)
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        forget_handles(eid)
        return next(x for x in planmod.proposals_with_state(db, eid, w.estate, w.snapshot_id, fstate.action_states(db, eid)) if x["id"] == p["id"])

    @app.delete("/api/estates/{eid}/plan/proposals/{pid}")
    def withdraw_proposal(request: Request, eid: str, pid: str):
        estate(eid)
        try:
            p = planmod.get_proposal(db, pid)
        except KeyError:
            raise HTTPException(404, "no such proposal")
        if p["estate_id"] != eid:
            raise HTTPException(404, "that proposal belongs to another estate")
        out = planmod.withdraw(db, pid, by=who(request))
        forget_handles(eid)
        return out

    # ---------- backlog 18: dimension inference and cell cost ----------
    app.state.dims = {}          # (snapshot id, model name) -> ModelDims; the parse does not change under a snapshot

    def _drop_snapshot_caches(sid: str) -> None:
        app.state.plans.pop(sid, None)
        lindex.drop(db, sid)                      # the line-item index is written from the parse: a rename or a re-parse makes it wrong
        for k in [k for k in app.state.dims if k[0] == sid]:
            app.state.dims.pop(k, None)

    def _dims(sid: str, model_name: str):
        key = (sid, model_name)
        md = app.state.dims.get(key)
        if md is None:
            er = run_of(sid)
            m = objmod.find_model(er, model_name)
            if m is None:
                raise HTTPException(404, f"no model named {model_name!r}")
            md = app.state.dims[key] = dimsmod.ModelDims(m, sid)
            while len(app.state.dims) > 12:
                app.state.dims.pop(next(iter(app.state.dims)))
        return md

    def _dims_item(eid: str, sid: str, model_name: str, ref: str) -> dict | None:
        try:
            return _dims(sid, model_name).item(ref)
        except Exception:
            return None

    def _with_size_states(eid: str, rep: dict) -> dict:
        """Every over-dimensioned row carries its key and the owner's decision on it, if any; the summary counts the decided."""
        st = fstate.size_states(db, eid)
        prefix = fstate.size_key(rep["model"], "")
        for r in rep["over"]:
            r["key"] = fstate.size_key(rep["model"], r["ref"])
            r["decision"] = st.get(r["key"])
        rep["over_summary"]["decided"] = sum(1 for k, v in st.items() if k.startswith(prefix) and v["state"] in ("keep_current_design", "done"))
        return rep

    @app.get("/api/estates/{eid}/size")
    def get_size(eid: str, model: str | None = None, limit: int = 300):
        """Why a model is the size it is: sizes solved from cell counts, what each axis costs, the over-dimensioned line items priced,
        each with the owner's decision on it if one was recorded."""
        w = workspace(eid)
        name = model or max(w.estate.models, key=lambda m: ((m.facts or {}).get("cells") or 0, m.name)).name
        return _with_size_states(eid, _dims(w.snapshot_id, name).summary(limit=max(1, min(limit, 2000))))

    @app.get("/api/estates/{eid}/size/item")
    def get_size_item(eid: str, model: str, ref: str):
        w = workspace(eid)
        j = _dims(w.snapshot_id, model).item(ref)
        if j is None:
            raise HTTPException(404, f"no line item named {ref!r} in {model}")
        m = objmod.find_model(run_of(w.snapshot_id), model)
        j["key"] = fstate.size_key(m.name if m else model, j["ref"])
        j["decision"] = fstate.size_states(db, eid).get(j["key"])
        return j

    @app.put("/api/estates/{eid}/size/state")
    def set_size_state(request: Request, eid: str, body: dict):
        """The owner's decision on an over-dimensioned line item (to review, investigating, done, keep current design) with the
        reason. It records their word; the architect then keeps the row apart and does not raise it again."""
        w = workspace(eid)
        model, ref = (body.get("model") or "").strip(), (body.get("ref") or "").strip()
        m = objmod.find_model(run_of(w.snapshot_id), model) if model else None
        j = _dims_item(eid, w.snapshot_id, m.name, ref) if (m and ref) else None
        if j is None:
            raise HTTPException(404, f"no line item named {ref!r} in {model!r}")
        try:
            rec = fstate.set_action_state(db, eid, fstate.size_key(m.name, j["ref"]), body.get("state") or "", body.get("reason") or "",
                                          by=who(request), snapshot_id=w.snapshot_id)
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        forget_state(eid)
        return rec

    return app


def serve(data: str, port: int = 8765, host: str = "127.0.0.1", api_key: str | None = None, model_id: str = "claude-sonnet-5"):
    import uvicorn
    app = create_app(data, api_key=api_key, model_id=model_id, host=host)
    b = app.state.backend
    if app.state.loopback and auth.no_accounts(app.state.db):
        print("  no accounts, bound to localhost: open to this machine. To let others in, create the owner and bind to the network:")
        print("  anaplan-architect users create --data DATA --owner --email you@example.com --name \"Your name\"; then serve --host 0.0.0.0")
    elif auth.no_accounts(app.state.db):
        print(f"  CLOSED: bound to {host} with no accounts. {CONSOLE_HINT}")
    imported = [x for x in app.state.legacy if x.get("status") == "active"]
    print(f"/architect, your Anaplan build buddy, at http://{host}:{port}  (data: {Path(data).resolve()}; backend: {b['provider']} {b['model'] or ''}"
          + (f" - {b['reason']}" if b['provider'] == 'none' else "") + (f"; imported {len(imported)} estate(s) from the old layout" if imported else "") + ")")
    for x in app.state.legacy:
        if x.get("status") != "active":
            print(f"  legacy import of {x.get('estate')}: {x.get('status')} {x.get('error') or ''}")
    if app.state.hosted:
        print("  hosted mode: Secure cookies, HSTS, forwarded scheme and address believed, API docs off")
    uvicorn.run(app, host=host, port=port, log_level="warning", **({"proxy_headers": True, "forwarded_allow_ips": "*"} if app.state.hosted else {}))
