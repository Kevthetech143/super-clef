"""Stat-keyed sha256 memo (ported from Super Jev hash-once, 566aa48). Clef has no file index; only the memo."""
import os
import sqlite3
import time
from pathlib import Path


class StatSha:
    """Stat-keyed sha256 memo kept in the principal's stat-sha.sqlite (works with the index flag off; never creates index.sqlite): a file's
    bytes are hashed once; a later ask reuses the sha only while (size, mtime_ns, ctime_ns, inode) are all
    unchanged. Any change, including a `touch -r` that restores mtime (ctime moves), means re-read.
    A file touched in the last RACY_NS is never memoized, so a write inside the clock tick cannot be missed."""
    RACY_NS = 50_000_000
    TABLE = ("CREATE TABLE IF NOT EXISTS statsha(path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, "
             "ctime_ns INTEGER, ino INTEGER, sha256 TEXT)")

    def __init__(self, db_path):
        import threading
        self.path = Path(db_path)
        self.rows, self.pending, self.loaded = {}, {}, False
        self.lock = threading.Lock()

    @staticmethod
    def key(path):
        st = os.stat(path)
        return (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino)

    def _load(self):
        if self.loaded:
            return
        self.loaded = True
        if not self.path.is_file():
            return
        try:
            db = sqlite3.connect(str(self.path), timeout=5)
            try:
                for r in db.execute("SELECT path,size,mtime_ns,ctime_ns,ino,sha256 FROM statsha"):
                    self.rows[r[0]] = (r[1:5], r[5])
            finally:
                db.close()
        except sqlite3.Error:
            pass  # no memo yet: every file is read once

    def get(self, path):
        """(key, sha or None): the memoized sha when the file's stat still matches, else None."""
        k = self.key(path)  # OSError (gone / unreadable) goes to the caller, as a read would
        with self.lock:
            self._load()
            hit = self.rows.get(path)
        return k, (hit[1] if hit and hit[0] == k else None)

    def put(self, path, k, sha):
        if time.time_ns() - max(k[1], k[2]) < self.RACY_NS:
            return
        with self.lock:
            self.rows[path] = (k, sha)
            self.pending[path] = (k, sha)

    def flush(self):
        with self.lock:
            batch, self.pending = self.pending, {}
        if not batch:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.path), timeout=5)
            try:
                db.execute(self.TABLE)
                db.executemany("INSERT OR REPLACE INTO statsha VALUES(?,?,?,?,?,?)",
                               [(p, *k, s) for p, (k, s) in batch.items()])
                db.commit()
            finally:
                db.close()
        except sqlite3.Error:
            pass  # the memo is an optimization only
