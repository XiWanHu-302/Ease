"""SQLite逐样本事件记录；不存图像。"""
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .core import KEYS, summarize


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, started TEXT NOT NULL,
                status TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (session_id INTEGER NOT NULL, t REAL NOT NULL,
                payload TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES sessions(id));
            CREATE INDEX IF NOT EXISTS sample_session ON samples(session_id, t);
        """)
        self.db.execute("UPDATE sessions SET status='interrupted' WHERE status='running'")
        self.db.commit()

    def settings(self):
        row = self.db.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def save_settings(self, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES(1,?)", (json.dumps(value),))
        self.db.commit()

    def start(self, metadata):
        cur = self.db.execute("INSERT INTO sessions(started,status,metadata) VALUES(?,?,?)",
                              (datetime.now(timezone.utc).isoformat(), "running", json.dumps(metadata)))
        self.db.commit()
        return cur.lastrowid

    def append(self, session, row):
        self.db.execute("INSERT INTO samples VALUES(?,?,?)", (session, row["t"], json.dumps(row)))

    def finish(self, session, status="finished"):
        self.db.execute("UPDATE sessions SET status=? WHERE id=?", (status, session))
        self.db.commit()

    def sessions(self):
        return self.db.execute("SELECT id,started,status FROM sessions ORDER BY id DESC").fetchall()

    def rows(self, session):
        return [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM samples WHERE session_id=? ORDER BY t", (session,))]

    def summary(self, session):
        return summarize(self.rows(session))

    def export(self, session, path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["elapsed_s", *KEYS, "pitch_delta_deg", "roll_delta_deg", "shoulder_delta_deg",
                             "yaw_deg", "nose_shoulder_ratio", "notices", "reasons", "latency_ms",
                             "pitch_raw_deg", "roll_raw_deg", "shoulder_raw_deg"])
            rows = self.rows(session)
            origin = rows[0]["t"] if rows else 0
            for row in rows:
                writer.writerow([round(row["t"] - origin, 3), *(row["states"][k] for k in KEYS),
                                 *(row.get("deltas", {}).get(k) for k in KEYS), row.get("yaw"), row.get("ratio"),
                                 ";".join(row.get("notices", [])), json.dumps(row.get("reasons", {}), ensure_ascii=False),
                                 row.get("latency_ms"), *(row.get("values", {}).get(k) for k in KEYS)])

    def clear(self):
        self.db.executescript("DELETE FROM samples; DELETE FROM sessions;")
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def close(self):
        self.db.commit()
        self.db.close()
