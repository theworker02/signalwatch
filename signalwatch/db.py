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
            con.execute('PRAGMA journal_mode=WAL')
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
                CREATE TABLE IF NOT EXISTS exoplanet_catalog (
                    name TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    disc_year INTEGER NOT NULL,
                    discoverymethod TEXT NOT NULL,
                    disc_facility TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
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
                CREATE TABLE IF NOT EXISTS investigation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL REFERENCES events(id),
                    state TEXT NOT NULL,
                    note TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_investigation_history_event
                    ON investigation_history(event_id,id);
                CREATE TABLE IF NOT EXISTS radio_files (
                    signature TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    state TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    candidate_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT
                );
                CREATE TABLE IF NOT EXISTS radio_observations (
                    filename TEXT PRIMARY KEY,
                    station TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    listed_uploaded_at TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    origin TEXT NOT NULL,
                    category TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_radio_observations_time ON radio_observations(observed_at DESC);
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=12)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=12000")
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

    def is_radio_file_processed(self, signature):
        with self.connect() as con:
            row=con.execute("SELECT state FROM radio_files WHERE signature=?",(signature,)).fetchone()
            return row is not None and row['state']=='ok'

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
            con.execute("""INSERT INTO investigation_history(event_id,state,note,updated_at)
                VALUES (?,?,?,?)""",(event_id,state,note,utcnow()))
        return True

    def event_by_id(self, event_id):
        with self.connect() as con:
            row=con.execute("""SELECT e.*,COALESCE(i.state,'new') review_state,
                COALESCE(i.note,'') review_note,i.updated_at review_updated_at
                FROM events e LEFT JOIN investigations i ON e.id=i.event_id
                WHERE e.id=?""",(event_id,)).fetchone()
            return dict(row,metadata=json.loads(row['metadata'])) if row else None

    def review_history(self,event_id):
        with self.connect() as con:
            return [dict(row) for row in con.execute("""SELECT id,event_id,state,note,updated_at
                FROM investigation_history WHERE event_id=? ORDER BY id""",(event_id,))]

    def event_changes(self,after_id=0,limit=100):
        with self.connect() as con:
            rows=con.execute("""SELECT e.*,COALESCE(i.state,'new') review_state FROM events e
                LEFT JOIN investigations i ON e.id=i.event_id
                WHERE e.id>? ORDER BY e.id ASC LIMIT ?""",(after_id,limit)).fetchall()
            return [dict(r,metadata=json.loads(r['metadata'])) for r in rows]

    def alerts(self,limit=50,min_score=60):
        # Test/synthetic and routine observations never enter the alert queue.
        with self.connect() as con:
            rows=con.execute("""SELECT e.*,COALESCE(i.state,'new') review_state
                FROM events e LEFT JOIN investigations i ON e.id=i.event_id
                WHERE e.score>=? AND e.severity NOT IN ('test','observation')
                  AND COALESCE(i.state,'new') NOT IN ('closed','likely_interference')
                ORDER BY e.id DESC LIMIT ?""",(min_score,limit)).fetchall()
            return [dict(r,metadata=json.loads(r['metadata'])) for r in rows]

    def solar_candidate_window(self):
        # Bounded query for research correlations; no cross-source ETI claim.
        with self.connect() as con:
            rows=con.execute("""SELECT * FROM events
                WHERE source='e-Callisto solar radio' AND severity != 'test'
                ORDER BY id DESC LIMIT 2000""").fetchall()
            return [dict(r,metadata=json.loads(r['metadata'])) for r in rows]

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

    def put_radio_observations(self, observations):
        """Store upload-index arrivals as observations, never as anomalies."""
        created=0
        with self.connect() as con:
            for record in observations:
                cursor=con.execute("""INSERT OR IGNORE INTO radio_observations
                    (filename,station,observed_at,listed_uploaded_at,discovered_at,size_bytes,origin,category)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (record['filename'],record['station'],record['observed_at'],
                     record['listed_uploaded_at'],utcnow(),record['size_bytes'],
                     record['origin'],record['category']))
                created+=cursor.rowcount
        return created

    def get_radio_observations(self, limit=50):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM radio_observations
                ORDER BY observed_at DESC LIMIT ?""",(limit,))]

    def store_exoplanet_catalog(self, items):
        """Record first seen in our catalog; do not equate this with planet discovery."""
        current=utcnow()
        with self.connect() as con:
            initial=con.execute('SELECT COUNT(*) FROM exoplanet_catalog').fetchone()[0]==0
            added=0
            for item in items:
                cur=con.execute("""INSERT OR IGNORE INTO exoplanet_catalog
                    (name,hostname,disc_year,discoverymethod,disc_facility,first_seen,last_seen)
                    VALUES (?,?,?,?,?,?,?)""",(item['name'],item['hostname'],item['disc_year'],
                       item['discoverymethod'],item['disc_facility'],current,current))
                added+=cur.rowcount
                con.execute('UPDATE exoplanet_catalog SET last_seen=? WHERE name=?',
                            (current,item['name']))
            # The initial snapshot is a baseline; subsequent changes mean only new *to us*.
            return 0 if initial else added

    def get_exoplanets(self,limit=100):
        with self.connect() as con:
            return [dict(r) for r in con.execute("""SELECT * FROM exoplanet_catalog
                ORDER BY disc_year DESC,name ASC LIMIT ?""",(limit,))]

    def get_radio_files(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM radio_files ORDER BY processed_at DESC LIMIT 40")]
