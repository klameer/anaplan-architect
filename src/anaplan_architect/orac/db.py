"""One SQLite file for everything the architect keeps, blobs aside.

WAL so readers never wait for a writer and two writers do not block each other for long (a second writer waits up to
30 seconds for the first, then fails); synchronous=NORMAL; foreign keys on; numbered
migrations in ./migrations applied at startup with the version kept in
PRAGMA user_version. Connections are per thread (the parse job runs in one).
"""
from __future__ import annotations
import datetime, json, secrets, sqlite3, threading
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"


def now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def new_id() -> str:
    """Time-ordered and not guessable: 20260925-141233-9f2c4a1b7d3e5f60. The date keeps ids readable and sortable; the
    64 random bits are what make one impossible to guess from the clock (ids appear in addresses and chat exports).
    Ids made before this (four hex digits at the end) still resolve."""
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(8)


class Db:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.applied = self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA synchronous=NORMAL")      # with WAL: a commit does not wait for the disk, and a crash loses at most the last moments, never the file
            self._local.conn = c
        return c

    def migrate(self) -> list[str]:
        c = self.conn
        have = c.execute("PRAGMA user_version").fetchone()[0]
        applied = []
        for f in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
            n = int(f.name[:3])
            if n <= have:
                continue
            c.executescript("BEGIN;\n" + f.read_text(encoding="utf-8") + f"\nPRAGMA user_version = {n};\nCOMMIT;")
            applied.append(f.name)
        return applied

    @property
    def version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    # ---------- small helpers ----------
    def q(self, sql: str, *args) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, *args) -> dict | None:
        r = self.conn.execute(sql, args).fetchone()
        return dict(r) if r else None

    def run(self, sql: str, *args) -> sqlite3.Cursor:
        return self.conn.execute(sql, args)

    @contextmanager
    def tx(self):
        """BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any exception. Nested use joins the outer transaction."""
        c = self.conn
        if c.in_transaction:
            yield c
            return
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def audit(self, workspace_id: str, action: str, target: str = "", detail=None, user_id: str | None = None) -> None:
        self.run("INSERT INTO audit(workspace_id, user_id, action, target, detail_json, at) VALUES (?,?,?,?,?,?)",
                 workspace_id, user_id, action, target, json.dumps(detail, default=str, ensure_ascii=False) if detail is not None else None, now())

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
