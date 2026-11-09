"""Append-only, hash-chained ledger (REVIEW P0-5).

Two classes of entry, never mixed in the UI:
  observed - written by the service itself from things it did or verified
  reported - claimed by the agent (free actions); untrusted, never "gold"
UPDATE/DELETE are blocked by triggers; the hash chain makes offline edits
detectable via verify().
"""
import hashlib
import json
import sqlite3
import threading

OBSERVED, REPORTED = "observed", "reported"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger(
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, cls TEXT NOT NULL CHECK(cls IN ('observed','reported')),
  kind TEXT NOT NULL, actor TEXT NOT NULL, data TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger
  BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""
GENESIS = "0" * 64


def _digest(prev, ts, cls, kind, actor, data):
    blob = json.dumps([prev, ts, cls, kind, actor, data], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


class Ledger:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock, clock):
        self.db, self.lock, self.clock = db, lock, clock
        with lock:
            db.executescript(SCHEMA)

    def append(self, cls: str, kind: str, actor: str, data: dict) -> int:
        data_s = json.dumps(data, sort_keys=True, default=str)
        with self.lock:
            row = self.db.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row[0] if row else GENESIS
            ts = self.clock()
            cur = self.db.execute(
                "INSERT INTO ledger(ts,cls,kind,actor,data,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
                (ts, cls, kind, actor, data_s, prev, _digest(prev, ts, cls, kind, actor, data_s)))
            self.db.commit()
            return cur.lastrowid

    def entries(self, after: int = 0):
        with self.lock:
            rows = self.db.execute(
                "SELECT seq,ts,cls,kind,actor,data FROM ledger WHERE seq>? ORDER BY seq", (after,)).fetchall()
        return [dict(seq=r[0], ts=r[1], cls=r[2], kind=r[3], actor=r[4], data=json.loads(r[5])) for r in rows]

    def verify(self) -> bool:
        """True iff the chain is intact. TODO: also anchor the head hash somewhere the DB owner can't rewrite."""
        prev = GENESIS
        with self.lock:
            rows = self.db.execute(
                "SELECT ts,cls,kind,actor,data,prev_hash,hash FROM ledger ORDER BY seq").fetchall()
        for ts, cls, kind, actor, data, p, h in rows:
            if p != prev or h != _digest(p, ts, cls, kind, actor, data):
                return False
            prev = h
        return True
