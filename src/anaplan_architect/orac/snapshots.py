"""A snapshot is the set of export files an estate is read from: one row per
(model, kind), each file a blob. The import flow is stage -> validate ->
process -> review coverage -> activate.

  draft       files being staged; each is validated as it arrives
  processing  a parse run is on it
  processed   parsed, coverage recorded, not yet the one the estate reads
  active      what the estate reads now; one per estate
  failed      the last parse run failed; the previously active snapshot still serves
  superseded  was active; kept so old conversations can resolve against it

A new draft inherits the active snapshot's files, so uploading one model's
fresh export makes a full snapshot with every other model unchanged, and the
per-file upload dates show which is which.
"""
from __future__ import annotations
import json, os, shutil, tempfile, threading, zipfile
from pathlib import Path
from .db import Db, now, new_id
from .blobs import BlobStore
from . import estates as reg

KINDS = ("line_items", "actions", "modules")
FILE_NAMES = {"line_items": "Line Items.csv", "actions": "Actions.csv", "modules": "Modules.csv"}
STATUSES = ("draft", "processing", "processed", "active", "failed", "superseded")
STAGEABLE = ("draft", "processed", "failed")
MAX_MB = float(os.environ.get("ARCHITECT_MAX_MB", "500"))
TIMEOUT_S = float(os.environ.get("ARCHITECT_TIMEOUT_S", "900"))
CACHE_RUNS = 4


class _Cancelled(Exception):
    pass


_ENGINE_FP: str | None = None


def engine_fingerprint() -> str:
    """The engine by content, not by version string. An editable install keeps its version while its code changes, and a
    run pickled by older code does not carry the fields newer code reads (a Finding with no `checks`): so the parse cache
    is keyed on the source of anaplan-estate and anaplan-grammar as they are on disk. Read once per process."""
    global _ENGINE_FP
    if _ENGINE_FP is None:
        import hashlib, importlib.util
        h = hashlib.sha1()
        for pkg in ("anaplan_estate", "anaplan_grammar"):
            spec = importlib.util.find_spec(pkg)
            root = Path(spec.origin).parent if spec and spec.origin else None
            for f in (sorted(root.rglob("*.py")) if root else []):
                h.update(f.relative_to(root).as_posix().encode("utf-8")); h.update(f.read_bytes())
        _ENGINE_FP = h.hexdigest()[:16]
    return _ENGINE_FP


class Reparsing(Exception):
    """The snapshot's parse cache is stale (its files, the model names, the aliases or the engine changed) and a background
    run is rebuilding it: the caller answers 409 and the page asks again in a moment."""

    def __init__(self, sid: str):
        super().__init__(f"snapshot {sid} is being re-read from its exports")
        self.sid = sid


def _check(kind: str, path: Path) -> str | None:
    """Validation before any parse. Line Items: the estate's own header/delimiter/Formula check. Others: not empty."""
    if kind == "line_items":
        from anaplan_estate.web import _quick_check
        return _quick_check(path)
    raw = path.read_bytes()[:65536]
    if not raw.strip():
        return f"'{path.name}' is empty."
    if len(raw.decode("utf-8", "replace").splitlines()) < 2:
        return f"'{path.name}' has a header row but no rows."
    return None


class Snapshots:
    def __init__(self, db: Db, blobs: BlobStore, data_root: str | Path, subprocess: bool = False):
        self.db = db
        self.blobs = blobs
        self.data = Path(data_root)
        self.subprocess = subprocess             # parse in a spawned process (Cancel can stop it); inline is faster to start
        self._runs: dict[str, object] = {}       # snapshot id -> EstateRun, most recent last
        self._lock = threading.Lock()
        self._sid_locks: dict[str, threading.Lock] = {}   # one load or re-parse per snapshot at a time
        self.refresher = None                    # sid -> {"running": True} | {"error": str}; set by the web layer (Jobs.refresh) so a
                                                 # stale cache is rebuilt in the background instead of inside a request

    # ---------- reading ----------
    def get(self, sid: str) -> dict:
        s = self.db.one("SELECT * FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        s["files"] = self.files(sid)
        s["run"] = self.last_run(sid)
        s["ready"] = self.ready(sid) if s["status"] in STAGEABLE else []
        s["references"] = self.references(sid)
        s["deletable"] = s["status"] not in ("active", "processing") and not any(s["references"].values())
        return s

    def list(self, eid: str) -> list[dict]:
        rows = self.db.q("SELECT s.*, (SELECT COUNT(*) FROM snapshot_files f WHERE f.snapshot_id=s.id) AS file_count, "
                         "(SELECT COUNT(DISTINCT model_id) FROM snapshot_files f WHERE f.snapshot_id=s.id) AS model_count, "
                         "(SELECT COUNT(*) FROM conversations c WHERE c.snapshot_id=s.id) AS held_conversations, "
                         "(SELECT COUNT(*) FROM citations x WHERE x.snapshot_id=s.id) AS citations "
                         "FROM snapshots s WHERE estate_id=? ORDER BY created DESC", eid)
        for r in rows:
            run = self.last_run(r["id"])
            r["run_status"] = run["status"] if run else None
            r["run_error"] = run["error"] if run else None
            r["deletable"] = r["status"] not in ("active", "processing") and not (r["held_conversations"] or r["citations"])
        return rows

    def references(self, sid: str) -> dict:
        """What still points at a snapshot: conversations held on it, citations read on it, proposals and decisions
        recorded on it. A superseded snapshot is kept while any of these is non-zero, so every old chip still opens."""
        return {"conversations": self.db.one("SELECT COUNT(*) AS n FROM conversations WHERE snapshot_id=?", sid)["n"],
                "citations": self.db.one("SELECT COUNT(*) AS n FROM citations WHERE snapshot_id=?", sid)["n"],
                "proposals": self.db.one("SELECT COUNT(*) AS n FROM proposals WHERE snapshot_id=? AND withdrawn_at IS NULL", sid)["n"],
                "decisions": self.db.one("SELECT COUNT(*) AS n FROM finding_state WHERE snapshot_id=?", sid)["n"]}

    def active(self, eid: str) -> dict | None:
        s = self.db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)
        return self.get(s["id"]) if s else None

    def files(self, sid: str) -> list[dict]:
        return self.db.q("SELECT f.*, m.name AS model, m.seq, b.bytes FROM snapshot_files f JOIN models m ON m.id=f.model_id "
                         "JOIN blobs b ON b.sha256=f.blob_sha WHERE f.snapshot_id=? ORDER BY m.seq, f.kind", sid)

    def last_run(self, sid: str) -> dict | None:
        r = self.db.one("SELECT * FROM parse_runs WHERE snapshot_id=? ORDER BY started DESC, rowid DESC LIMIT 1", sid)
        return self._run_dict(r) if r else None

    def run(self, rid: str) -> dict:
        r = self.db.one("SELECT * FROM parse_runs WHERE id=?", rid)
        if not r:
            raise KeyError(rid)
        return self._run_dict(r)

    @staticmethod
    def _run_dict(r: dict) -> dict:
        r["stats"] = json.loads(r.pop("stats_json") or "null")
        r["coverage"] = json.loads(r.pop("coverage_json") or "null")
        return r

    def ready(self, sid: str) -> list[str]:
        """Why the snapshot cannot be processed; empty when it can."""
        files = self.files(sid)
        if not files:
            return ["no files staged"]
        out = []
        with_li = {f["model_id"] for f in files if f["kind"] == "line_items"}
        for f in files:
            if f["problem"]:
                out.append(f"{f['model']}: {f['problem']}")
            if f["model_id"] not in with_li:
                out.append(f"{f['model']}: has a {FILE_NAMES[f['kind']]} but no Line Items export")
        return sorted(set(out))

    # ---------- staging ----------
    def create(self, eid: str, label: str = "", note: str = "", created_by: str | None = None, inherit: bool = True, created: str | None = None) -> dict:
        e = reg.get_estate(self.db, eid)
        if not e:
            raise KeyError(eid)
        sid = new_id()
        with self.db.tx():
            self.db.run("INSERT INTO snapshots(id, estate_id, label, created_by, created, status, note) VALUES (?,?,?,?,?,?,?)",
                        sid, eid, (label or "").strip()[:120], created_by, created or now(), "draft", (note or "").strip())
            if inherit:
                act = self.db.one("SELECT id FROM snapshots WHERE estate_id=? AND status='active'", eid)
                if act:      # every file of the active snapshot, except those of models since retired
                    self.db.run("INSERT INTO snapshot_files(snapshot_id, model_id, kind, blob_sha, original_name, uploaded_at, problem) "
                                "SELECT ?, f.model_id, f.kind, f.blob_sha, f.original_name, f.uploaded_at, f.problem FROM snapshot_files f "
                                "JOIN models m ON m.id=f.model_id WHERE f.snapshot_id=? AND m.retired=0", sid, act["id"])
        self.db.audit(e["workspace_id"], "snapshot.create", sid, {"estate": eid, "label": label, "inherit": inherit}, created_by)
        return self.get(sid)

    def _stageable(self, sid: str) -> dict:
        s = self.db.one("SELECT * FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        if s["status"] not in STAGEABLE:
            raise ValueError(f"snapshot is {s['status']}: its files cannot change; make a new snapshot")
        return s

    def stage(self, sid: str, model_id: str, kind: str, data: bytes, original_name: str = "", uploaded_at: str | None = None, by: str | None = None) -> dict:
        s = self._stageable(sid)
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        m = reg.get_model(self.db, model_id)
        if not m or m["estate_id"] != s["estate_id"]:
            raise ValueError("that model is not in this estate")
        name = Path(original_name or "").name or FILE_NAMES[kind]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / name
            p.write_bytes(data)
            problem = _check(kind, p)
        stamp = uploaded_at or now()
        with self.blobs.lock:                    # the file and the row that refers to it go in as one step: a clear-out cannot land between them
            sha = self.blobs.put(data)
            with self.db.tx():
                self.db.run("INSERT OR REPLACE INTO snapshot_files(snapshot_id, model_id, kind, blob_sha, original_name, uploaded_at, problem) VALUES (?,?,?,?,?,?,?)",
                            sid, model_id, kind, sha, name, stamp, problem)
                if s["status"] != "draft":
                    self.db.run("UPDATE snapshots SET status='draft' WHERE id=?", sid)
        self._forget(sid)
        e = reg.get_estate(self.db, s["estate_id"])
        self.db.audit(e["workspace_id"], "snapshot.stage", sid, {"model": m["name"], "kind": kind, "name": name, "bytes": len(data), "problem": problem}, by)
        return {"snapshot_id": sid, "model_id": model_id, "model": m["name"], "kind": kind, "blob_sha": sha, "original_name": name,
                "uploaded_at": stamp, "problem": problem, "bytes": len(data)}

    def unstage(self, sid: str, model_id: str, kind: str | None = None) -> int:
        s = self._stageable(sid)
        if kind:
            n = self.db.run("DELETE FROM snapshot_files WHERE snapshot_id=? AND model_id=? AND kind=?", sid, model_id, kind).rowcount
        else:
            n = self.db.run("DELETE FROM snapshot_files WHERE snapshot_id=? AND model_id=?", sid, model_id).rowcount
        if s["status"] != "draft":
            self.db.run("UPDATE snapshots SET status='draft' WHERE id=?", sid)
        self._forget(sid)
        return n

    def stage_zip(self, sid: str, zip_path: str | Path, make_model, by: str | None = None) -> list[dict]:
        """One folder per model inside the zip, as anaplan-estate reads it. Folder names that match a
        model or one of its aliases stage into that model; the rest go to make_model(name)."""
        from anaplan_estate.web import _extract_zip, Budget, TooLarge
        from anaplan_estate.fleet import discover
        s = self._stageable(sid)
        staged = []
        with tempfile.TemporaryDirectory() as td:
            try:
                _extract_zip(Path(zip_path), Path(td), Budget(int(MAX_MB * 1024 * 1024)))
            except TooLarge:
                raise ValueError(f"the zip expands beyond {MAX_MB:.0f} MB")
            except zipfile.BadZipFile:
                raise ValueError("that is not a zip file")
            specs = discover(td)
            if not specs:
                raise ValueError("the zip holds no 'Line Items*.csv'; put one folder per model in it")
            for spec in specs:
                m = reg.find_model(self.db, s["estate_id"], spec["name"]) or make_model(spec["name"])
                for kind in KINDS:
                    p = spec.get(kind)
                    if p:
                        staged.append(self.stage(sid, m["id"], kind, Path(p).read_bytes(), Path(p).name, by=by))
        return staged

    # ---------- files on disk for the engine ----------
    def root(self, sid: str) -> Path:
        s = self.db.one("SELECT estate_id FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        return self.data / "estates" / s["estate_id"] / "snapshots" / sid

    def materialise(self, sid: str) -> tuple[Path, dict[str, str]]:
        """Write the snapshot's files where fleet.discover finds them: one folder per model named
        '<seq> <model id>', so fleet's folder-name cleaning cannot collide two models; the returned
        names map turns each id back into the model's registered name."""
        root = self.root(sid)
        files = self.files(sid)
        names: dict[str, str] = {}
        wanted = set()
        for f in files:
            folder = f"{f['seq']:03d} {f['model_id']}"
            wanted.add(folder)
            dest = root / folder / FILE_NAMES[f["kind"]]
            if not dest.exists() or dest.stat().st_size != f["bytes"]:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.blobs.path(f["blob_sha"]), dest)
            names[f["model_id"]] = f["model"]
        if root.exists():
            for d in root.iterdir():
                if d.is_dir() and d.name not in wanted:
                    shutil.rmtree(d, ignore_errors=True)
            # estate.pkl / estate.key / result.json / spec.json beside the folders are the parse cache; left alone
            for d in root.iterdir():
                if d.is_dir():
                    keep = {FILE_NAMES[f["kind"]] for f in files if f"{f['seq']:03d} {f['model_id']}" == d.name}
                    for x in d.iterdir():
                        if x.name not in keep:
                            x.unlink(missing_ok=True)
        return root, names

    # ---------- processing ----------
    def start_run(self, sid: str) -> str:
        rid = new_id()
        self.db.run("INSERT INTO parse_runs(id, snapshot_id, started, status) VALUES (?,?,?,'running')", rid, sid, now())
        return rid

    def cache_key(self, sid: str, names: dict[str, str]) -> str:
        """Everything the parse depends on: the files (by content), the model names, the aliases, the engine (its version and its source)."""
        import hashlib
        s = self.db.one("SELECT estate_id FROM snapshots WHERE id=?", sid)
        parts = [f"{f['seq']}|{f['model_id']}|{f['kind']}|{f['blob_sha']}" for f in self.files(sid)]
        parts += [f"name|{k}|{v}" for k, v in sorted(names.items())]
        parts += [f"alias|{k}|{v}" for k, v in sorted(reg.aliases_map(self.db, s["estate_id"]).items())]
        try:
            from importlib.metadata import version
            parts.append("estate|" + version("anaplan-estate") + "|grammar|" + version("anaplan-grammar"))
        except Exception:
            parts.append("estate|unknown")
        parts.append("engine|" + engine_fingerprint())
        import sys
        parts.append("py|" + sys.version.split()[0])
        return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()

    def _parse(self, sid: str, cancelled=None) -> tuple[object, dict]:
        """Materialise, then parse: inline, or in a spawned process that Cancel can terminate.
        Returns (EstateRun, result dict). Raises on failure."""
        from . import parsework
        s = self.db.one("SELECT estate_id FROM snapshots WHERE id=?", sid)
        root, names = self.materialise(sid)
        aliases = reg.aliases_map(self.db, s["estate_id"])
        key = self.cache_key(sid, names)
        if not self.subprocess:
            res = parsework.work(str(root), aliases, names, key)
            er = parsework.load(root, key)
            return er, res
        import multiprocessing, subprocess, sys, time
        spec = root / "spec.json"
        spec.write_text(json.dumps({"aliases": aliases, "names": names}), encoding="utf-8")
        (root / "result.json").unlink(missing_ok=True)
        proc = subprocess.Popen([sys.executable, "-m", "anaplan_architect.orac.parsework", str(root), key, str(spec)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        started = time.time()
        while proc.poll() is None:
            if cancelled and cancelled():
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise _Cancelled()
            if time.time() - started > TIMEOUT_S:
                proc.kill()
                raise TimeoutError(f"parse ran longer than {TIMEOUT_S:.0f}s and was stopped (ARCHITECT_TIMEOUT_S)")
            time.sleep(0.2)
        err = (proc.stderr.read() if proc.stderr else "") or ""
        try:
            res = json.loads((root / "result.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise RuntimeError(f"the parse process ended without a result (exit {proc.returncode}): {err[-800:]}")
        if not res.get("ok"):
            raise RuntimeError(res.get("error") or f"parse failed (exit {proc.returncode})")
        er = parsework.load(root, key)
        if er is None:
            raise RuntimeError("the parse process wrote no usable estate.pkl")
        return er, res

    def process(self, sid: str, run_id: str | None = None, cancelled=None, by: str | None = None) -> dict:
        """Parse the snapshot through anaplan-estate. Synchronous; Jobs wraps it in a thread.
        The active snapshot is never touched: a failure leaves it serving."""
        s = self.db.one("SELECT * FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        rid = run_id or self.start_run(sid)
        e = reg.get_estate(self.db, s["estate_id"])
        try:
            if s["status"] not in STAGEABLE:
                raise ValueError(f"snapshot is {s['status']}")
            why = self.ready(sid)
            if why:
                raise ValueError("; ".join(why))
            self.db.run("UPDATE snapshots SET status='processing' WHERE id=?", sid)
            er, res = self._parse(sid, cancelled)
        except _Cancelled:
            self.db.run("UPDATE parse_runs SET finished=?, status='cancelled' WHERE id=?", now(), rid)
            self.db.run("UPDATE snapshots SET status='draft' WHERE id=?", sid)
            self.db.audit(e["workspace_id"], "snapshot.process", sid, {"run": rid, "status": "cancelled"}, by)
            return self.run(rid)
        except BaseException as ex:      # SystemExit included: fleet raises it on a folder it cannot read
            msg = f"{type(ex).__name__}: {ex}"[:2000]
            self.db.run("UPDATE parse_runs SET finished=?, status='failed', error=? WHERE id=?", now(), msg, rid)
            self.db.run("UPDATE snapshots SET status='failed' WHERE id=? AND status IN ('processing','draft','processed','failed')", sid)
            self.db.audit(e["workspace_id"], "snapshot.process", sid, {"run": rid, "status": "failed", "error": msg}, by)
            return self.run(rid)
        if cancelled and cancelled():
            self.db.run("UPDATE parse_runs SET finished=?, status='cancelled' WHERE id=?", now(), rid)
            self.db.run("UPDATE snapshots SET status='draft' WHERE id=?", sid)
            return self.run(rid)
        self._remember(sid, er)
        with self.db.tx():
            self.db.run("UPDATE parse_runs SET finished=?, status='ok', stats_json=?, coverage_json=? WHERE id=?",
                        now(), json.dumps(res["stats"], default=str, ensure_ascii=False), json.dumps(res["coverage"], default=str, ensure_ascii=False), rid)
            self.db.run("UPDATE snapshots SET status='processed' WHERE id=?", sid)
        self.db.audit(e["workspace_id"], "snapshot.process", sid, {"run": rid, "status": "ok"}, by)
        return self.run(rid)

    def _sid_lock(self, sid: str) -> threading.Lock:
        with self._lock:
            lk = self._sid_locks.get(sid)
            if lk is None:
                lk = self._sid_locks[sid] = threading.Lock()
            return lk

    def estate_run(self, sid: str, block: bool = False):
        """The parsed estate for a snapshot: from memory, else from the estate.pkl the last parse wrote (if it was made
        from exactly these files, names and aliases), else parsed again. One load per snapshot at a time: the parallel
        first requests of a page wait for one load instead of each unpickling a copy. A stale cache is parsed again in
        the background when a refresher is set and block is False (Reparsing is raised for the caller to answer 409 and
        the page to ask again); otherwise it is parsed now, bounded by the subprocess timeout where parsing runs in one."""
        with self._lock:
            er = self._runs.get(sid)
        if er is not None:
            return er
        lk = self._sid_lock(sid)
        if not (lk.acquire(timeout=10) if (self.refresher is not None and not block) else lk.acquire()):
            raise Reparsing(sid)                 # a re-read (or a long load) holds the snapshot: the page asks again in a moment
        try:
            with self._lock:
                er = self._runs.get(sid)         # loaded by the request we waited for
            if er is not None:
                return er
            from . import parsework
            s = self.db.one("SELECT estate_id FROM snapshots WHERE id=?", sid)
            if not s:
                raise KeyError(sid)
            root, names = self.materialise(sid)
            key = self.cache_key(sid, names)
            er = parsework.load(root, key)
            if er is None:
                if not block and self.refresher is not None:
                    st = self.refresher(sid) or {}
                    if st.get("error"):
                        raise RuntimeError("the exports could not be re-read: " + st["error"])
                    raise Reparsing(sid)
                er, _ = self._parse(sid)
            self._remember(sid, er)
        finally:
            lk.release()
        return er

    def reparse(self, sid: str) -> None:
        """Rebuild a snapshot's parse cache from its exports: the background half of estate_run. Statuses are untouched."""
        with self._sid_lock(sid):
            er, _ = self._parse(sid)
            self._remember(sid, er)

    def _remember(self, sid: str, er) -> None:
        with self._lock:
            self._runs.pop(sid, None)
            self._runs[sid] = er
            while len(self._runs) > CACHE_RUNS:
                self._runs.pop(next(iter(self._runs)))

    def _forget(self, sid: str) -> None:
        with self._lock:
            self._runs.pop(sid, None)

    # ---------- activation and deletion ----------
    def activate(self, sid: str, by: str | None = None) -> dict:
        s = self.db.one("SELECT * FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        if s["status"] == "active":
            return self.get(sid)
        if s["status"] != "processed":
            raise ValueError(f"snapshot is {s['status']}; it must be processed without error before it can be activated")
        run = self.last_run(sid)
        if not run or run["status"] != "ok":
            raise ValueError("the last parse run did not succeed")
        with self.db.tx():
            self.db.run("UPDATE snapshots SET status='superseded', superseded_at=? WHERE estate_id=? AND status='active'", now(), s["estate_id"])
            self.db.run("UPDATE snapshots SET status='active', activated_at=? WHERE id=?", now(), sid)
        e = reg.get_estate(self.db, s["estate_id"])
        self.db.audit(e["workspace_id"], "snapshot.activate", sid, {"estate": s["estate_id"]}, by)
        return self.get(sid)

    def delete(self, sid: str, by: str | None = None) -> dict:
        """Removes a snapshot the estate does not read: its rows, its materialised folder and its parse cache, then
        the blobs nothing references any more. A superseded snapshot goes only when nothing points at it (no
        conversation held on it, no citation read on it, no proposal or decision recorded on it); otherwise the old
        answers would lose the evidence they open. The active snapshot never goes."""
        s = self.db.one("SELECT * FROM snapshots WHERE id=?", sid)
        if not s:
            raise KeyError(sid)
        if s["status"] in ("active", "processing"):
            raise ValueError(f"a {s['status']} snapshot is kept")
        refs = self.references(sid)
        if s["status"] == "superseded" and any(refs.values()):
            kept = ", ".join(f"{v} {k}" for k, v in refs.items() if v)
            raise ValueError(f"this superseded snapshot is kept: {kept} still point at it")
        root = self.root(sid)
        with self.db.tx():
            self.db.run("DELETE FROM snapshots WHERE id=?", sid)
        self._forget(sid)
        shutil.rmtree(root, ignore_errors=True)
        gc = self.blobs.gc()
        e = reg.get_estate(self.db, s["estate_id"])
        self.db.audit(e["workspace_id"], "snapshot.delete", sid, {"status": s["status"], "blobs_removed": gc}, by)
        return {"deleted": sid, "estate": s["estate_id"], "blobs_removed": gc}

