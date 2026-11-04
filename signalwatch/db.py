"""SQLite storage: source health, immutable evidence references and events."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_url TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    discovered_at TEXT NOT NULL,
                    UNIQUE(source, source_id)
                );
                CREATE INDEX IF NOT EXISTS ix_events_time ON events(observed_at DESC);
                CREATE TABLE IF NOT EXISTS samples (
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    metric REAL NOT NULL,
                    unit TEXT NOT NULL,
                    PRIMARY KEY(source, observed_at)
                );
                CREATE TABLE IF NOT EXISTS sources (
                    name TEXT PRIMARY KEY,
                    url TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_attempt TEXT,
                    last_success TEXT,
                    last_error TEXT,
                    records_seen INTEGER NOT NULL DEFAULT 0,
                    new_events INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS investigations (
                    event_id INTEGER PRIMARY KEY REFERENCES events(id),
                    state TEXT NOT NULL CHECK(state IN ('new','investigating','likely_interference','needs_followup','closed')),
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS radio_files (
                    signature TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT
                );
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=12)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def put_event(self, *, source, source_id, kind, title, observed_at, score,
                  severity, summary, evidence_url=None, metadata=None):
        with self.connect() as con:
            cur = con.execute("""
                INSERT OR IGNORE INTO events
                (source,source_id,kind,title,observed_at,score,severity,summary,evidence_url,metadata,discovered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (source, str(source_id), kind, title, observed_at, float(score),
                  severity, summary, evidence_url, json.dumps(metadata or {}, default=str), utcnow()))
            return cur.rowcount > 0

    def put_samples(self, source, samples, unit):
        with self.connect() as con:
            con.executemany("INSERT OR IGNORE INTO samples VALUES (?,?,?,?)",
                            [(source, t, float(v), unit) for t, v in samples])
            cutoff=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(timespec='seconds')
            con.execute('DELETE FROM samples WHERE source=? AND observed_at < ?', (source, cutoff))

    def source_status(self, name, url, *, status, records_seen=0, new_events=0, error=None):
        now = utcnow()
        with self.connect() as con:
            con.execute("""
                INSERT INTO sources(name,url,status,last_attempt,last_success,last_error,records_seen,new_events)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    url=excluded.url, status=excluded.status, last_attempt=excluded.last_attempt,
                    last_success=CASE WHEN excluded.status='ok' THEN excluded.last_success ELSE sources.last_success END,
                    last_error=excluded.last_error, records_seen=excluded.records_seen,
                    new_events=excluded.new_events
            """, (name,url,status,now,now if status == 'ok' else None,error,records_seen,new_events))

    def has_radio_file(self, signature):
        with self.connect() as con:
            return con.execute("SELECT 1 FROM radio_files WHERE signature=?", (signature,)).fetchone() is not None

    def record_radio_file(self, signature, filename, state, count=0, message=''):
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO radio_files VALUES (?,?,?,?,?,?)",
                        (signature, filename, state, utcnow(), count, message[:1000]))

    def recent_events(self, limit=100, source=None, kind=None):
        clauses, params = [], []
        if source:
            clauses.append('e.source=?'); params.append(source)
        if kind:
            clauses.append('e.kind=?'); params.append(kind)
        where = 'WHERE ' + ' AND '.join(clauses) if clauses else ''
        sql = f"""SELECT e.*, COALESCE(i.state,'new') review_state, COALESCE(i.note,'') review_note,
                   i.updated_at review_updated_at FROM events e
                   LEFT JOIN investigations i ON e.id=i.event_id {where}
                   ORDER BY CASE WHEN e.source='NASA JPL' THEN e.discovered_at ELSE e.observed_at END DESC,
                            e.id DESC LIMIT ?"""
        with self.connect() as con:
            rows = con.execute(sql, (*params, limit)).fetchall()
            return [dict(r, metadata=json.loads(r['metadata'])) for r in rows]

    def review_event(self, event_id, state, note):
        allowed = {'new','investigating','likely_interference','needs_followup','closed'}
        if state not in allowed: raise ValueError('Invalid review state')
        if len(note)>2000: raise ValueError('Review note exceeds 2000 characters')
        with self.connect() as con:
            if con.execute('SELECT 1 FROM events WHERE id=?',(event_id,)).fetchone() is None:
                return False
            con.execute("""INSERT INTO investigations(event_id,state,note,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET state=excluded.state,note=excluded.note,
                    updated_at=excluded.updated_at""",(event_id,state,note,utcnow()))
        return True

    def events_count(self):
        with self.connect() as con:
            rows = con.execute("SELECT severity,COUNT(*) n FROM events GROUP BY severity").fetchall()
            total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            radio_count = con.execute("SELECT COUNT(*) FROM radio_files WHERE state='ok'").fetchone()[0]
        return {'total':total,'by_severity':{r['severity']:r['n'] for r in rows},'radio_files_processed':radio_count}

    def get_samples(self, source, limit=240):
        with self.connect() as con:
            rows = con.execute("SELECT * FROM samples WHERE source=? ORDER BY observed_at DESC LIMIT ?", (source,limit)).fetchall()
            return list(reversed([dict(r) for r in rows]))

    def get_sources(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY name")]

    def get_radio_files(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM radio_files ORDER BY processed_at DESC LIMIT 40")]
