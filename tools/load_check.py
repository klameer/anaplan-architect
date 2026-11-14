"""Several people at once: does one instance hold?

Starts a real server process on a scratch store, with a made-up model behind it (an OpenAI-compatible endpoint run by
this tool: no key, no cost), signs in N logins and has each of them work at the same time for a while: two workspaces
each, exports and documents uploaded, questions asked that call tools, workspaces switched, backups taken, chats
deleted. A probe signs in over and over to time the sign-in page while the others work.

  .venv/Scripts/python tools/load_check.py [--logins 8] [--seconds 180] [--big-mb 0] [--json out/load-check.json]

What it asserts (the exit code is 1 when any fails):
  - no answer is a 5xx, and "database is locked" appears nowhere: not in a response, not in the server's log
  - nothing crosses: every workspace carries its own marker in its model names and documents; every request the model
    receives, every answer, every list and every citation holds the asker's marker and no other; another login's
    workspace is a 404
  - the spend ledger has exactly one row per model call that returned, per login
  - sign-in stays quick (p95 under a second), measured over the whole run and separately while every login has a
    question in flight
  - at the limit a person is told to try again (429 with a plain message), never an error page

`run()` is what the tests call with fewer logins and seconds (tests/test_load.py).
"""
from __future__ import annotations
import argparse, http.server, json, os, pathlib, random, re, socket, sqlite3, statistics, subprocess, sys, tempfile, threading, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "estate"
STORES = ROOT / "examples" / "caldergate" / "stores" / "Line Items.csv"
MARK = re.compile(r"LCMARK[a-z0-9]+")
ADMIN, ADMIN_PW, LOGIN_PW = "loadadmin", "load-check-admin-pw-1", "load-check-login-pw-1"       # a scratch store's logins, made and thrown away here


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def peak_rss_mb(pid: int) -> float | None:
    """The most memory the process has held, in MB: the working-set peak on Windows, VmHWM on Linux."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(n, ctypes.c_size_t) for n in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            k32 = ctypes.WinDLL("kernel32", use_last_error=True); psapi = ctypes.WinDLL("psapi", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            h = k32.OpenProcess(0x1000 | 0x0010, False, pid)
            if not h:
                return None
            c = PMC(); c.cb = ctypes.sizeof(PMC)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            ok = psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb)
            k32.CloseHandle(h)
            return round(c.PeakWorkingSetSize / 1e6, 1) if ok else None
        for ln in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
            if ln.startswith("VmHWM:"):
                return round(int(ln.split()[1]) / 1e3, 1)
    except Exception:
        return None
    return None


# ---------- the made-up model: an OpenAI-compatible chat-completions endpoint ----------
class FakeModel:
    """Answers like a model that calls two tools and then says what it was shown. It keeps count of the calls it
    answered per workspace marker, and notes any request that carried more than one marker: that would be one
    workspace's material reaching another's question."""

    def __init__(self, think: float = 0.35):
        self.think, self.lock = think, threading.Lock()
        self.calls: dict[str, int] = {}
        self.crossed: list[str] = []
        self.unmarked = 0
        self.slow = 0.0                 # extra seconds per call while the storm phase runs
        self.limit: set[str] = set()    # markers whose calls are refused with 429, as a provider's rate limit would
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                status, out = fake.answer(json.loads(raw or b"{}"), raw.decode("utf-8", "replace"))
                body = json.dumps(out).encode()
                self.send_response(status); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body)))
                self.end_headers(); self.wfile.write(body)

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):      # a caller that hung up at the end of the run
                pass

        self.srv = Quiet(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/v1"

    def answer(self, req: dict, raw: str) -> tuple[int, dict]:
        marks = set(MARK.findall(raw))
        if marks & self.limit:
            return 429, {"error": {"message": "Rate limit reached for requests", "type": "rate_limit_error", "code": "rate_limit_exceeded"}}
        time.sleep(self.think + self.slow)
        msgs = req.get("messages") or []
        shown = set()
        for m in msgs:
            if m.get("role") in ("system", "tool"):
                shown |= set(MARK.findall(json.dumps(m)))
        asked = next((m.get("content") or "" for m in reversed(msgs) if m.get("role") == "user"), "")
        mine = (MARK.findall(asked) or sorted(marks) or [""])[0]
        if req.get("tools") and not any(m.get("role") == "tool" for m in msgs[-3:]):
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_a" + str(random.random())[2:10], "type": "function", "function": {"name": "search_documents", "arguments": json.dumps({"query": mine or "steering"})}},
                {"id": "call_b" + str(random.random())[2:10], "type": "function", "function": {"name": "list_models", "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
            msg = {"role": "assistant", "content": "What the workspace shows. CONTEXT-MARKERS: " + ",".join(sorted(shown)) + " END"}
            finish = "stop"
        with self.lock:
            if len(marks) > 1:
                self.crossed.append(",".join(sorted(marks)))
            if marks:
                for m in marks:
                    self.calls[m] = self.calls.get(m, 0) + 1
            else:
                self.unmarked += 1
        return 200, {"id": "chatcmpl-load", "object": "chat.completion", "model": req.get("model") or "load-model",
                     "choices": [{"index": 0, "message": msg, "finish_reason": finish}], "usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140}}


# ---------- the server under test ----------
class Server:
    def __init__(self, model_url: str, extra_env: dict | None = None):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="architect-load-"))
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = dict(os.environ)
        env.update({"ARCHITECT_PROVIDER": "openai", "OPENAI_BASE_URL": model_url, "OPENAI_API_KEY": "none-needed", "ARCHITECT_MODEL": "load-model",
                    "ARCHITECT_ADMIN_USER": ADMIN, "ARCHITECT_ADMIN_PASSWORD": ADMIN_PW, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
                    # nothing of this machine's own setup reaches the scratch server: no real key, no tracing
                    "ANTHROPIC_API_KEY": "", "LANGSMITH_API_KEY": "", "LANGCHAIN_API_KEY": "", "LANGSMITH_TRACING": "", "ARCHITECT_OPEN": "", "ARCHITECT_DEMO": "", "ARCHITECT_HOSTED": ""})
        env.update(extra_env or {})
        self.log = open(self.dir / "server.log", "w", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, "-m", "anaplan_architect.cli", "serve", "--data", str(self.dir / "data"), "--port", str(self.port)],
                                     cwd=str(self.dir), env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def wait(self, seconds: float = 60) -> None:
        import httpx
        end = time.time() + seconds
        while time.time() < end:
            if self.proc.poll() is not None:
                raise RuntimeError("the server stopped while starting:\n" + self.log_text()[-2000:])
            try:
                if httpx.get(self.base + "/health", timeout=2).status_code == 200:
                    return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError("the server did not answer /health in time")

    def pid(self) -> int:
        """The process that serves. On Windows a virtual environment's python is a launcher: the server is its child."""
        if os.name == "nt":
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={self.proc.pid}').ProcessId"],
                                     capture_output=True, text=True, timeout=20).stdout.split()
                kids = [int(x) for x in out if x.isdigit()]
                if kids:
                    return kids[0]
            except Exception:
                pass
        return self.proc.pid

    def log_text(self) -> str:
        if not self.log.closed:
            self.log.flush()
        return (self.dir / "server.log").read_text(encoding="utf-8", errors="replace")

    def stop(self) -> None:
        if os.name == "nt":                                    # the launcher and the server under it
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True)
        else:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()
        self.log.close()


# ---------- one login at work ----------
class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows: list[tuple[str, int, float]] = []          # kind, status, seconds
        self.fails: list[str] = []
        self.busy: dict[str, int] = {}
        self.in_flight = 0
        self.probe: list[tuple[float, bool]] = []             # seconds, taken while every login had a question in flight

    def add(self, kind: str, status: int, secs: float, body: str = "") -> None:
        with self.lock:
            self.rows.append((kind, status, secs))
            if status >= 500 or "database is locked" in body.lower():
                self.fails.append(f"{kind}: {status} {body[:200]}")
            if status == 429:
                self.busy[kind] = self.busy.get(kind, 0) + 1

    def fail(self, what: str) -> None:
        with self.lock:
            self.fails.append(what)


def p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 3)


class Login:
    def __init__(self, base: str, n: int, stats: Stats):
        import httpx
        self.n, self.name, self.stats = n, f"lc{n:02d}", stats
        self.c = httpx.Client(base_url=base, timeout=180)
        self.uid = None
        self.ws: list[dict] = []                               # {"id", "mark", "chats": []}
        self.rng = random.Random(1000 + n)
        self.asked = 0

    def marks(self) -> set[str]:
        return {w["mark"] for w in self.ws}

    def call(self, kind: str, method: str, url: str, ok=(200,), **kw):
        if method != "GET":
            kw.setdefault("headers", {})["x-csrf"] = self.c.cookies.get("csrf") or ""
        t = time.time()
        try:
            r = self.c.request(method, url, **kw)
        except Exception as ex:
            self.stats.add(kind, 599, time.time() - t, f"{type(ex).__name__}: {ex}")
            return None
        self.stats.add(kind, r.status_code, time.time() - t, r.text[:400] if r.status_code >= 400 else "")
        if r.status_code not in ok and r.status_code != 429 and r.status_code < 500:
            self.stats.fail(f"{self.name} {kind}: {r.status_code} {r.text[:200]}")
        return r

    def own_only(self, kind: str, text: str, want: str | None = None) -> None:
        seen = set(MARK.findall(text))
        if seen - self.marks():
            self.stats.fail(f"{self.name} {kind}: another workspace's marker came back: {sorted(seen - self.marks())}")
        if want and want not in seen:
            self.stats.fail(f"{self.name} {kind}: the workspace's own marker {want} is missing")

    def sign_in(self) -> None:
        r = self.call("sign-in", "POST", "/api/auth/login", json={"email": self.name, "password": LOGIN_PW})
        if r is None or r.status_code != 200:
            raise RuntimeError(f"{self.name} could not sign in")

    def make_workspace(self, i: int, big: bytes | None = None) -> None:
        mark = f"LCMARKu{self.n:02d}w{i}"
        files, names = [], []
        if big is not None:
            files.append(("line_items", ("Line Items.csv", big, "text/csv"))); names.append(f"Big {mark}")
        elif i == 2 and STORES.exists():                       # the second workspace is the larger demo model: 5,403 line items
            files.append(("line_items", ("Line Items.csv", STORES.read_bytes(), "text/csv"))); names.append(f"Stores {mark}")
        else:
            for d in sorted(FIXTURES.iterdir()):
                files.append(("line_items", ("Line Items.csv", (d / "Line Items.csv").read_bytes(), "text/csv")))
                files.append(("actions", ("Actions.csv", (d / "Actions.csv").read_bytes(), "text/csv")))
                names.append(f"{d.name.split(' ', 1)[1]} {mark}")
        for attempt in range(40):                               # at the limit the server says try again: a person would
            r = self.call("upload-exports", "POST", "/api/estates", data={"name": f"Load {mark}", "model_names": names}, files=files)
            if r is not None and r.status_code == 429:
                time.sleep(1.0); continue
            break
        if r is None or r.status_code != 200:
            raise RuntimeError(f"{self.name} could not create a workspace: {getattr(r, 'status_code', None)} {getattr(r, 'text', '')[:300]}")
        self.ws.append({"id": r.json()["id"], "mark": mark, "chats": []})
        self.upload_document(self.ws[-1])

    def upload_document(self, w: dict) -> None:
        k = self.rng.randrange(10 ** 6)
        text = (f"# Steering note {w['mark']} {k}\n\n## Decision\n\nThe group agreed {w['mark']} keeps the mapping in the formula until the audit closes. "
                f"Reference {k}.\n\n## Why\n\nBecause {w['mark']} was the only owner who could test it in the window.\n").encode()
        r = self.call("upload-document", "POST", f"/api/estates/{w['id']}/documents", files=[("files", (f"Steering {w['mark']} {k}.md", text, "text/markdown"))])
        if r is not None and r.status_code == 200:
            self.own_only("upload-document", r.text, w["mark"])

    def ask(self, w: dict, cid: str | None = None) -> None:
        q = f"Why does {w['mark']} keep the mapping in the formula?"
        if cid is None:
            r = self.call("new-chat", "POST", f"/api/estates/{w['id']}/conversations", json={"title": q})
            if r is None or r.status_code != 200:
                return
            cid = r.json()["id"]; w["chats"].append(cid)
        t = time.time(); done = None; status = 0; body = ""
        with self.stats.lock:
            self.stats.in_flight += 1
        try:
            with self.c.stream("POST", f"/api/conversations/{cid}/stream", json={"text": q}, headers={"x-csrf": self.c.cookies.get("csrf") or ""}) as r:
                status = r.status_code
                if status != 200:
                    body = r.read().decode("utf-8", "replace")
                else:
                    for line in r.iter_lines():
                        if line.startswith("data: "):
                            ev = json.loads(line[6:])
                            if ev.get("type") == "done":
                                done = ev
                            elif ev.get("type") == "error":
                                body = ev.get("message", "")
        except Exception as ex:
            status, body = 599, f"{type(ex).__name__}: {ex}"
        finally:
            with self.stats.lock:
                self.stats.in_flight -= 1
        self.stats.add("ask", status, time.time() - t, body)
        if status == 429 or status == 409:
            return
        if status != 200 or done is None:
            self.stats.fail(f"{self.name} ask: {status} {body[:200] or 'the stream ended without an answer'}")
            return
        self.asked += 1
        shown = set(MARK.findall(done["text"].split("CONTEXT-MARKERS:")[-1]))
        if shown != {w["mark"]}:
            self.stats.fail(f"{self.name} ask in {w['mark']}: the model was shown {sorted(shown)}")
        turn = done.get("turn") or {}
        self.own_only("ask", json.dumps(turn), w["mark"])
        for c in (turn.get("citations") or [])[:3]:
            cid_ = c.get("id") if isinstance(c, dict) else c
            if cid_:
                rc = self.call("citation", "GET", f"/api/citations/{cid_}")
                if rc is not None and rc.status_code == 200:
                    self.own_only("citation", rc.text)

    def switch(self) -> None:
        r = self.call("list-workspaces", "GET", "/api/estates")
        if r is not None and r.status_code == 200:
            self.own_only("list-workspaces", r.text)
            if {e["id"] for e in r.json()} != {w["id"] for w in self.ws}:
                self.stats.fail(f"{self.name} list-workspaces: sees {len(r.json())} workspaces, owns {len(self.ws)}")
        w = self.rng.choice(self.ws)
        for kind, url in (("open-workspace", f"/api/estates/{w['id']}"), ("list-chats", f"/api/estates/{w['id']}/conversations"), ("list-documents", f"/api/estates/{w['id']}/documents")):
            r = self.call(kind, "GET", url)
            if r is not None and r.status_code == 200:
                self.own_only(kind, r.text, w["mark"] if kind != "list-chats" else None)

    def backup(self, w: dict) -> None:
        r = self.call("backup", "GET", f"/api/estates/{w['id']}/backup")
        if r is not None and r.status_code == 200 and not r.content.startswith(b"PK"):
            self.stats.fail(f"{self.name} backup: not a zip")

    def come_and_go(self) -> None:
        """A third workspace: exports read while everyone else works, then deleted by name."""
        mark = f"LCMARKu{self.n:02d}w3"
        d = sorted(FIXTURES.iterdir())[0]
        r = self.call("upload-exports", "POST", "/api/estates", data={"name": f"Temp {mark}", "model_names": [f"Temp {mark}"]},
                      files=[("line_items", ("Line Items.csv", (d / "Line Items.csv").read_bytes(), "text/csv"))])
        if r is not None and r.status_code == 200:
            self.call("delete-workspace", "DELETE", f"/api/estates/{r.json()['id']}", json={"confirm": f"Temp {mark}"})

    def flood(self, w: dict) -> dict:
        """Four questions at the same moment from one login: the limit answers some and tells the rest to wait."""
        seen = {"answered": 0, "told_to_wait": 0, "message": ""}
        chats = []
        for _ in range(4):
            r = self.call("new-chat", "POST", f"/api/estates/{w['id']}/conversations", json={"title": "flood"})
            if r is not None and r.status_code == 200:
                chats.append(r.json()["id"])
        import httpx

        def one(cid):
            c = httpx.Client(base_url=str(self.c.base_url), timeout=120, cookies=dict(self.c.cookies))
            r = c.post(f"/api/conversations/{cid}/messages", json={"text": f"Why does {w['mark']} keep the mapping?"}, headers={"x-csrf": self.c.cookies.get("csrf") or ""})
            self.stats.add("flood-ask", r.status_code, r.elapsed.total_seconds(), r.text[:300] if r.status_code >= 400 else "")
            with self.stats.lock:
                if r.status_code == 200:
                    seen["answered"] += 1
                elif r.status_code == 429:
                    seen["told_to_wait"] += 1; seen["message"] = r.json().get("detail", "")
            c.close()
        ts = [threading.Thread(target=one, args=(cid,)) for cid in chats]
        [t.start() for t in ts]; [t.join() for t in ts]
        w["chats"] += chats
        return seen

    def delete_chat(self, w: dict) -> None:
        if w["chats"]:
            self.call("delete-chat", "DELETE", f"/api/conversations/{w['chats'].pop(0)}", ok=(200, 204))

    def trespass(self, others: list["Login"]) -> None:
        o = self.rng.choice(others)
        if o.ws:
            r = self.call("other-workspace", "GET", f"/api/estates/{self.rng.choice(o.ws)['id']}", ok=(404,))
            if r is not None and r.status_code == 200:
                self.stats.fail(f"{self.name} opened {o.name}'s workspace")

    def work(self, until: float, others: list["Login"]) -> None:
        while time.time() < until:
            w = self.rng.choice(self.ws); x = self.rng.random()
            if x < 0.40:
                self.ask(w)
            elif x < 0.50 and w["chats"]:
                self.ask(w, self.rng.choice(w["chats"]))
            elif x < 0.60:
                self.upload_document(w)
            elif x < 0.80:
                self.switch()
            elif x < 0.85:
                self.backup(w)
            elif x < 0.92:
                self.delete_chat(w)
            elif x < 0.95:
                self.come_and_go()
            else:
                self.trespass(others)
            time.sleep(self.rng.random() * 0.3)


def run(logins: int = 8, seconds: float = 180, big_mb: int = 0, think: float = 0.35, extra_env: dict | None = None, say=print) -> dict:
    """The whole check. Returns the report; report["failures"] is empty when the instance held."""
    import httpx
    fake = FakeModel(think)
    srv = Server(fake.url, extra_env)
    stats = Stats()
    report: dict = {"logins": logins, "seconds": seconds}
    try:
        srv.wait()
        pid = srv.pid()
        admin = httpx.Client(base_url=srv.base, timeout=60)
        r = admin.post("/api/auth/login", json={"email": ADMIN, "password": ADMIN_PW}); assert r.status_code == 200, r.text
        hdr = {"x-csrf": admin.cookies.get("csrf") or ""}
        people = [Login(srv.base, i + 1, stats) for i in range(logins)]
        for p in people + [Login(srv.base, 99, stats)]:
            r = admin.post("/api/admin/users", json={"username": p.name, "name": p.name, "password": LOGIN_PW, "cap_usd": None, "demo": False}, headers=hdr)
            assert r.status_code == 200, r.text
            p.uid = r.json()["user"]["id"]

        stop = threading.Event()

        def probe():
            while not stop.is_set():
                c = httpx.Client(base_url=srv.base, timeout=30); t = time.time()
                try:
                    r = c.post("/api/auth/login", json={"email": "lc99", "password": LOGIN_PW}); c.get("/api/auth/me")
                    stats.add("probe-sign-in", r.status_code, time.time() - t, r.text[:200] if r.status_code >= 400 else "")
                    with stats.lock:
                        stats.probe.append((time.time() - t, stats.in_flight >= logins))
                except Exception as ex:
                    stats.add("probe-sign-in", 599, time.time() - t, str(ex))
                finally:
                    c.close()
                stop.wait(0.2)

        def each(fn):
            errs = []

            def go(p):
                try:
                    fn(p)
                except Exception as ex:
                    errs.append(f"{p.name}: {type(ex).__name__}: {ex}")
            ts = [threading.Thread(target=go, args=(p,)) for p in people]
            [t.start() for t in ts]; [t.join() for t in ts]
            for e in errs:
                stats.fail(e)

        t0 = time.time()
        threading.Thread(target=probe, daemon=True).start()
        say(f"{logins} logins signing in and making two workspaces each, at once")
        each(lambda p: (p.sign_in(), p.make_workspace(1), p.make_workspace(2)))
        report["setup_seconds"] = round(time.time() - t0, 1)

        say("every login asks at the same moment (the model is slow on purpose), while the probe signs in")
        fake.slow = 2.0
        each(lambda p: p.ask(p.ws[0]))
        fake.slow = 0.0

        say(f"mixed work for {seconds:.0f}s")
        until = time.time() + seconds
        each(lambda p: p.work(until, [o for o in people if o is not p]))

        say("every login asks at the same moment again")
        fake.slow = 2.0
        each(lambda p: p.ask(p.ws[1]))
        fake.slow = 0.0

        # a provider's rate limit, as the person who hit it sees it
        victim = people[0]
        fake.limit = {victim.ws[0]["mark"]}
        r = victim.c.post(f"/api/estates/{victim.ws[0]['id']}/conversations", json={"title": "rate limited"}, headers={"x-csrf": victim.c.cookies.get("csrf") or ""})
        with victim.c.stream("POST", f"/api/conversations/{r.json()['id']}/stream", json={"text": f"Why does {victim.ws[0]['mark']} do that?"}, headers={"x-csrf": victim.c.cookies.get("csrf") or ""}) as s:
            report["rate_limit_seen"] = {"status": s.status_code, "body": s.read().decode("utf-8", "replace")[-400:]}
        fake.limit = set()

        say("one login asks four questions at the same moment")
        fake.slow = 1.0
        report["flood"] = people[-1].flood(people[-1].ws[0])
        fake.slow = 0.0
        if not report["flood"]["told_to_wait"] or not report["flood"]["answered"]:
            stats.fail(f"four questions at once from one login: {report['flood']} (some should be answered and the rest told to wait)")

        if big_mb:
            say(f"four logins each upload a {big_mb} MB export at the same moment")
            row = STORES.read_text(encoding="utf-8").splitlines()
            head, rows = row[0], row[1:]
            out, size, k = [head], len(head), 0
            while size < big_mb * 1024 * 1024:
                for ln in rows:
                    out.append(ln); size += len(ln) + 1
                k += 1
            big = "\n".join(out).encode()
            before = peak_rss_mb(pid)
            tb = time.time()
            ts = [threading.Thread(target=lambda p=p: p.call("big-upload", "POST", "/api/estates", ok=(200, 400), data={"name": f"Big {p.name}", "model_names": [f"Big LCMARKu{p.n:02d}w9"]},
                                                              files=[("line_items", ("Line Items.csv", big, "text/csv"))])) for p in people[:4]]
            [t.start() for t in ts]; [t.join() for t in ts]
            report["big_upload"] = {"mb_each": round(len(big) / 1e6, 1), "at_once": len(ts), "seconds": round(time.time() - tb, 1), "peak_rss_mb_before": before, "peak_rss_mb_after": peak_rss_mb(pid),
                                    "statuses": [s for k_, s, _ in stats.rows if k_ == "big-upload"]}

        stop.set(); time.sleep(0.5)
        report["peak_rss_mb"] = peak_rss_mb(pid)

        # the ledger: one row per model call that returned, per login
        db = sqlite3.connect(str(srv.dir / "data" / "orac.db"))
        rows = dict(db.execute("SELECT user_id, COUNT(*) FROM spend GROUP BY user_id").fetchall())
        db.close()
        ledger = {}
        for p in people:
            made = sum(n for m, n in fake.calls.items() if m.startswith(f"LCMARKu{p.n:02d}w"))
            ledger[p.name] = {"model_calls": made, "ledger_rows": rows.get(p.uid, 0)}
            if made != rows.get(p.uid, 0):
                stats.fail(f"{p.name}: {made} model calls returned, {rows.get(p.uid, 0)} rows on the spend ledger")
        if fake.crossed:
            stats.fail(f"the model was sent more than one workspace's marker in one request, {len(fake.crossed)} time(s): {fake.crossed[:3]}")
        if fake.unmarked:
            stats.fail(f"{fake.unmarked} model call(s) carried no workspace marker")
        log = srv.log_text()
        if "database is locked" in log.lower():
            stats.fail("the server's log has 'database is locked'")
        if "Traceback" in log:
            stats.fail("the server's log has a traceback: " + log[log.index("Traceback"):][:600])

        by: dict[str, list] = {}
        for kind, status, secs in stats.rows:
            by.setdefault(kind, []).append((status, secs))
        report["requests"] = len(stats.rows)
        report["errors_5xx"] = sum(1 for _, s, _ in stats.rows if s >= 500)
        report["busy_429"] = stats.busy
        report["limits"] = "2 answers in flight per login, 16 on the instance, 2 sets of exports read at once (the defaults)"
        report["by_kind"] = {k: {"n": len(v), "p50": round(statistics.median(s for _, s in v), 3), "p95": p95([s for _, s in v]), "max": round(max(s for _, s in v), 3)} for k, v in sorted(by.items())}
        every = [s for s, _ in stats.probe]; storm = [s for s, st in stats.probe if st]
        report["sign_in"] = {"samples": len(every), "p95": p95(every), "max": round(max(every), 3) if every else 0,
                             "while_all_ask": {"samples": len(storm), "p95": p95(storm), "max": round(max(storm), 3) if storm else 0}}
        if not every or p95(every) >= 1.0:
            stats.fail(f"sign-in p95 was {p95(every)}s over the run ({len(every)} samples): it must stay under a second")
        if every and max(every) >= 3.0:
            stats.fail(f"one sign-in took {max(every):.1f}s: something held the whole server up")
        if not storm:
            stats.fail("no sign-in was timed while every login had a question in flight")
        elif p95(storm) >= 1.0:
            stats.fail(f"sign-in p95 was {p95(storm)}s while every login had a question in flight ({len(storm)} samples)")
        report["questions_answered"] = sum(p.asked for p in people)
        report["model_calls"] = sum(fake.calls.values())
        report["ledger"] = ledger
    finally:
        srv.stop()
        report["server_log_tail"] = srv.log_text()[-1500:]
    report["failures"] = stats.fails
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logins", type=int, default=8); ap.add_argument("--seconds", type=float, default=180); ap.add_argument("--big-mb", type=int, default=0)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    rep = run(a.logins, a.seconds, a.big_mb)
    if a.json:
        pathlib.Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.json).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"\n{rep['logins']} logins, {rep.get('requests', 0)} requests, {rep.get('questions_answered', 0)} questions answered, {rep.get('model_calls', 0)} model calls")
    print(f"5xx: {rep.get('errors_5xx')}   told to try again (429): {rep.get('busy_429')}   peak memory: {rep.get('peak_rss_mb')} MB")
    si = rep.get("sign_in") or {}
    print(f"sign-in p95 {si.get('p95')}s over {si.get('samples')} samples; while every login asks: p95 {(si.get('while_all_ask') or {}).get('p95')}s over {(si.get('while_all_ask') or {}).get('samples')}")
    for k, v in (rep.get("by_kind") or {}).items():
        print(f"  {k:18} n={v['n']:5}  p50 {v['p50']:7.3f}s  p95 {v['p95']:7.3f}s  max {v['max']:7.3f}s")
    if rep.get("big_upload"):
        print("big upload:", rep["big_upload"])
    print("rate limit, as seen:", rep.get("rate_limit_seen"))
    for f in rep["failures"][:40]:
        print("FAILED:", f)
    print("held" if not rep["failures"] else f"{len(rep['failures'])} failure(s)")
    return 1 if rep["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
