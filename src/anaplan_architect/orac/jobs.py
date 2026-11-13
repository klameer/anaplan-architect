"""Background parse runs. One worker: parsing is CPU-bound and two runs at once
would only slow each other. The run row in parse_runs is the progress record;
cancel marks a run so its result is discarded when the engine returns (the
engine itself cannot be interrupted).
"""
from __future__ import annotations
import threading, time
from concurrent.futures import Future, ThreadPoolExecutor
from .snapshots import Snapshots


class Jobs:
    def __init__(self, snapshots: Snapshots):
        self.snaps = snapshots
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="orac-parse")
        self.futures: dict[str, Future] = {}
        self.cancel_flags: dict[str, bool] = {}
        self.refresh_failed: dict[str, tuple[float, str]] = {}   # sid -> (when, error) of the last re-read that failed
        self.lock = threading.Lock()

    def running(self, sid: str) -> bool:
        f = self.futures.get(sid)
        return bool(f and not f.done())

    def submit(self, sid: str, by: str | None = None) -> dict:
        """Start a parse run for the snapshot, or return the one already running."""
        with self.lock:
            if self.running(sid):
                return self.snaps.last_run(sid)
            why = self.snaps.ready(sid)
            if why:
                raise ValueError("; ".join(why))
            rid = self.snaps.start_run(sid)
            self.cancel_flags[sid] = False
            self.futures[sid] = self.pool.submit(self.snaps.process, sid, rid, lambda: self.cancel_flags.get(sid, False), by)
        return self.snaps.run(rid)

    def cancel(self, sid: str) -> bool:
        with self.lock:
            if not self.running(sid):
                return False
            self.cancel_flags[sid] = True
            return True

    def wait(self, sid: str, timeout: float = 120) -> dict | None:
        f = self.futures.get(sid)
        if f:
            f.result(timeout=timeout)
        return self.snaps.last_run(sid)

    # ---------- the parse cache of a snapshot that is not being processed (estate_run found it stale) ----------
    def refresh(self, sid: str) -> dict:
        """Rebuild a snapshot's parse cache in the background. One run per snapshot at a time; a run that failed is not
        tried again for 30 seconds, and its error is handed back instead of a new run."""
        with self.lock:
            k = "refresh:" + sid
            f = self.futures.get(k)
            if f and not f.done():
                return {"running": True}
            err = self.refresh_failed.get(sid)
            if err and time.time() - err[0] < 30:
                return {"error": err[1]}
            self.refresh_failed.pop(sid, None)
            self.futures[k] = self.pool.submit(self._refresh, sid)
            return {"running": True}

    def _refresh(self, sid: str) -> None:
        try:
            self.snaps.reparse(sid)
        except BaseException as ex:
            self.refresh_failed[sid] = (time.time(), f"{type(ex).__name__}: {ex}"[:400])
            raise

    def wait_refresh(self, sid: str, timeout: float = 120) -> None:
        f = self.futures.get("refresh:" + sid)
        if f:
            f.result(timeout=timeout)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
