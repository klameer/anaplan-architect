"""Content-addressed files: <root>/aa/bb/<sha256>. A file is written once,
however many snapshots reference it; the blobs table keeps size and time.

Several people use one store at once. Each write goes through a temporary name of its own (two people sending the
same file at the same moment do not collide), and `lock` is held from writing a file until the row that refers to it
is in: `gc` takes the same lock, so a clear-out never takes a file that is on its way in.
"""
from __future__ import annotations
import hashlib, os, secrets, shutil, threading
from pathlib import Path
from .db import Db, now

CHUNK = 1 << 18


class BlobStore:
    def __init__(self, root: str | Path, db: Db):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.lock = threading.RLock()        # held by whoever is writing a file and the row that refers to it; and by gc

    def path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha[2:4] / sha

    def _land(self, p: Path, write) -> None:
        """Write a file under a name of this write's own, then move it into place. If someone else's identical copy got
        there first, theirs stands."""
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.part")
        try:
            write(tmp)
            try:
                tmp.replace(p)
            except OSError:
                if not p.exists():
                    raise
        finally:
            tmp.unlink(missing_ok=True)

    def put(self, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        p = self.path(sha)
        if not p.exists():
            self._land(p, lambda tmp: tmp.write_bytes(data))
        self.db.run("INSERT OR IGNORE INTO blobs(sha256, bytes, stored_at) VALUES (?,?,?)", sha, len(data), now())
        return sha

    def put_file(self, src: str | Path) -> str:
        h = hashlib.sha256(); n = 0
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(CHUNK), b""):
                h.update(chunk); n += len(chunk)
        sha = h.hexdigest()
        p = self.path(sha)
        if not p.exists():
            self._land(p, lambda tmp: shutil.copyfile(src, tmp))
        self.db.run("INSERT OR IGNORE INTO blobs(sha256, bytes, stored_at) VALUES (?,?,?)", sha, n, now())
        return sha

    def get(self, sha: str) -> bytes:
        return self.path(sha).read_bytes()

    def exists(self, sha: str) -> bool:
        return self.path(sha).exists()

    def size(self, sha: str) -> int | None:
        row = self.db.one("SELECT bytes FROM blobs WHERE sha256=?", sha)
        return row["bytes"] if row else None

    def gc(self) -> int:
        """Remove blobs no snapshot file references. Returns how many."""
        with self.lock:
            rows = self.db.q("SELECT sha256 FROM blobs WHERE sha256 NOT IN (SELECT blob_sha FROM snapshot_files)")
            for r in rows:
                p = self.path(r["sha256"])
                if p.exists():
                    p.unlink()
                self.db.run("DELETE FROM blobs WHERE sha256=?", r["sha256"])
            return len(rows)
