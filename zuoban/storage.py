"""SQLite逐样本事件记录；不存图像。"""
import csv
import json
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core import KEYS, summarize
from .journey import station_for


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
            CREATE TABLE IF NOT EXISTS journey_settings (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS day_stats (
                session_id INTEGER NOT NULL, day TEXT NOT NULL, eligible INTEGER NOT NULL,
                active REAL NOT NULL DEFAULT 0, union_time REAL NOT NULL DEFAULT 0,
                pitch_alert REAL NOT NULL DEFAULT 0, roll_alert REAL NOT NULL DEFAULT 0,
                shoulder_alert REAL NOT NULL DEFAULT 0,
                pitch_notice INTEGER NOT NULL DEFAULT 0, roll_notice INTEGER NOT NULL DEFAULT 0,
                shoulder_notice INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(session_id, day));
            CREATE INDEX IF NOT EXISTS day_stats_day ON day_stats(day);
            CREATE TABLE IF NOT EXISTS day_stats_built (session_id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS journey_completions (
                day TEXT PRIMARY KEY, journey INTEGER NOT NULL, station INTEGER NOT NULL,
                earned_at TEXT NOT NULL);
        """)
        self._live = {}
        self.db.execute("UPDATE sessions SET status='interrupted' WHERE status='running'")
        self._backfill_days()
        self.db.commit()

    @staticmethod
    def _day(epoch):
        return datetime.fromtimestamp(epoch).date().isoformat()

    @staticmethod
    def _next_midnight(epoch):
        following = datetime.fromtimestamp(epoch).date() + timedelta(days=1)
        return time.mktime((following.year, following.month, following.day, 0, 0, 0, 0, 0, -1))

    def _touch_day(self, session, day, eligible):
        self.db.execute("INSERT OR IGNORE INTO day_stats(session_id,day,eligible) VALUES(?,?,?)",
                        (session, day, int(eligible)))

    def _ingest(self, session, row, anchor, previous, eligible):
        epoch = anchor + row["t"]
        day = self._day(epoch)
        self._touch_day(session, day, eligible)
        for key in row.get("notices", []):
            if key in KEYS:
                self.db.execute(f"UPDATE day_stats SET {key}_notice={key}_notice+1 WHERE session_id=? AND day=?",
                                (session, day))
        if previous is None:
            return {day}
        remaining = min(0.5, max(0.0, row["t"] - previous["t"]))
        cursor = anchor + previous["t"]
        touched = {day}
        states = previous["states"]
        while remaining > 1e-9:
            span = min(remaining, max(0.001, self._next_midnight(cursor) - cursor))
            segment_day = self._day(cursor)
            self._touch_day(session, segment_day, eligible)
            values = [
                span if any(state in ("normal", "pending", "alert") for state in states.values()) else 0,
                span if "alert" in states.values() else 0,
                *(span if states.get(key) == "alert" else 0 for key in KEYS),
                session, segment_day,
            ]
            self.db.execute("""UPDATE day_stats SET active=active+?, union_time=union_time+?,
                pitch_alert=pitch_alert+?, roll_alert=roll_alert+?, shoulder_alert=shoulder_alert+?
                WHERE session_id=? AND day=?""", values)
            touched.add(segment_day)
            cursor += span
            remaining -= span
        return touched

    def _backfill_days(self):
        """首次升级时逐会话建日索引；不对历史会话补发关卡。"""
        missing = self.db.execute("""SELECT id,started,metadata FROM sessions
            WHERE id NOT IN (SELECT session_id FROM day_stats_built)""").fetchall()
        for session, started, metadata in missing:
            self.db.execute("DELETE FROM day_stats WHERE session_id=?", (session,))
            rows = self.db.execute("SELECT payload FROM samples WHERE session_id=? ORDER BY t", (session,))
            previous = None
            anchor = None
            eligible = bool(json.loads(metadata).get("journey_enabled", False))
            for (payload,) in rows:
                row = json.loads(payload)
                if anchor is None:
                    anchor = datetime.fromisoformat(started).timestamp() - row["t"]
                self._ingest(session, row, anchor, previous, eligible)
                previous = row
            self.db.execute("INSERT OR IGNORE INTO day_stats_built VALUES(?)", (session,))

    def journey_enabled(self):
        row = self.db.execute("SELECT enabled FROM journey_settings WHERE id=1").fetchone()
        return bool(row[0]) if row else True

    def set_journey_enabled(self, enabled):
        self.db.execute("INSERT OR REPLACE INTO journey_settings VALUES(1,?)", (int(enabled),))
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
        self._live[cur.lastrowid] = (None, None, bool(metadata.get("journey_enabled", False)))
        return cur.lastrowid

    def append(self, session, row):
        self.db.execute("INSERT INTO samples VALUES(?,?,?)", (session, row["t"], json.dumps(row)))
        anchor, previous, eligible = self._live[session]
        if anchor is None:
            started = self.db.execute("SELECT started FROM sessions WHERE id=?", (session,)).fetchone()[0]
            anchor = datetime.fromisoformat(started).timestamp() - row["t"]
        touched = self._ingest(session, row, anchor, previous, eligible)
        self._live[session] = (anchor, row, eligible)
        unlocked = [day for day in sorted(touched) if eligible and self.journey_enabled() and self._unlock(day)]
        if unlocked:
            self.db.commit()  # 解锁提示出现前，连同触发它的样本一起持久化。
        return unlocked

    def _unlock(self, day):
        if self.db.execute("SELECT 1 FROM journey_completions WHERE day=?", (day,)).fetchone():
            return False
        count = self.db.execute("SELECT COUNT(*) FROM journey_completions").fetchone()[0]
        journey, station, goal = station_for(count)
        active = self.db.execute("SELECT COALESCE(SUM(active),0) FROM day_stats WHERE day=? AND eligible=1",
                                 (day,)).fetchone()[0]
        if active + 1e-6 < goal * 60:
            return False
        self.db.execute("INSERT INTO journey_completions VALUES(?,?,?,?)",
                        (day, journey, station, datetime.now(timezone.utc).isoformat()))
        return True

    def finish(self, session, status="finished"):
        self.db.execute("UPDATE sessions SET status=? WHERE id=?", (status, session))
        self.db.execute("INSERT OR IGNORE INTO day_stats_built VALUES(?)", (session,))
        self._live.pop(session, None)
        self.db.commit()

    def month_days(self, year, month):
        first = date(year, month, 1)
        end = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        return {day: {"active": active, "completed": bool(completed)}
                for day, active, completed in self.db.execute("""SELECT d.day, SUM(d.active),
                    EXISTS(SELECT 1 FROM journey_completions c WHERE c.day=d.day)
                    FROM day_stats d WHERE d.day>=? AND d.day<? GROUP BY d.day""",
                    (first.isoformat(), end.isoformat()))}

    def day_summary(self, day):
        row = self.db.execute("""SELECT COUNT(*), COALESCE(SUM(active),0), COALESCE(SUM(union_time),0),
            COALESCE(SUM(pitch_alert),0), COALESCE(SUM(roll_alert),0), COALESCE(SUM(shoulder_alert),0),
            COALESCE(SUM(pitch_notice),0), COALESCE(SUM(roll_notice),0), COALESCE(SUM(shoulder_notice),0)
            FROM day_stats WHERE day=?""", (day,)).fetchone()
        return {"sessions": row[0], "active": row[1], "union": row[2],
                "alerts": dict(zip(KEYS, row[3:6])), "notices": dict(zip(KEYS, row[6:9]))}

    def day_sessions(self, day):
        return self.db.execute("""SELECT s.id,s.started,s.status FROM sessions s
            JOIN day_stats d ON d.session_id=s.id WHERE d.day=? ORDER BY s.started DESC""", (day,)).fetchall()

    def journey_progress(self, day):
        count = self.db.execute("SELECT COUNT(*) FROM journey_completions").fetchone()[0]
        journey, station, goal = station_for(count)
        active = self.db.execute("SELECT COALESCE(SUM(active),0) FROM day_stats WHERE day=? AND eligible=1",
                                 (day,)).fetchone()[0]
        completed = self.db.execute("SELECT journey,station FROM journey_completions WHERE day=?", (day,)).fetchone()
        return {"journey": journey, "station": station, "goal": goal, "today_active": active,
                "completed_today": completed, "total_completed": count}

    def journey_history(self, limit=7):
        return self.db.execute("""SELECT day,journey,station FROM journey_completions
            ORDER BY earned_at DESC LIMIT ?""", (limit,)).fetchall()

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
        self.db.executescript("""DELETE FROM samples; DELETE FROM sessions;
            DELETE FROM day_stats; DELETE FROM day_stats_built; DELETE FROM journey_completions;""")
        self._live.clear()
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def close(self):
        self.db.commit()
        self.db.close()
