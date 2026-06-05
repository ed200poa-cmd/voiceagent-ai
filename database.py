import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("voiceagent.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id  TEXT PRIMARY KEY,
                started_at  TEXT NOT NULL,
                ended_at    TEXT,
                status      TEXT DEFAULT 'active',
                service_type TEXT,
                caller_name  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS turns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                text        TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id     TEXT NOT NULL,
                name           TEXT,
                phone          TEXT,
                address        TEXT,
                service_type   TEXT,
                preferred_time TEXT,
                is_emergency   INTEGER DEFAULT 0,
                created_at     TEXT NOT NULL
            )
        """)
        conn.commit()


def create_session(session_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, started_at) VALUES (?, ?)",
            (session_id, datetime.utcnow().isoformat()),
        )
        conn.commit()


def end_session(session_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = 'ended' WHERE session_id = ?",
            (datetime.utcnow().isoformat(), session_id),
        )
        conn.commit()


def log_turn(session_id: str, role: str, text: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO turns (session_id, role, text, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, text, datetime.utcnow().isoformat()),
        )
        conn.commit()


def save_appointment(session_id: str, data: dict) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """INSERT INTO appointments
               (session_id, name, phone, address, service_type, preferred_time, is_emergency, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                data.get("name"),
                data.get("phone"),
                data.get("address"),
                data.get("service_type"),
                data.get("preferred_time"),
                1 if data.get("is_emergency") else 0,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.execute(
            "UPDATE sessions SET service_type = ?, caller_name = ?, status = 'booked' WHERE session_id = ?",
            (data.get("service_type"), data.get("name"), session_id),
        )
        conn.commit()
        return cur.lastrowid


def get_all_sessions() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50").fetchall()
        result = []
        for row in rows:
            s = dict(row)
            turns = conn.execute(
                "SELECT role, text, timestamp FROM turns WHERE session_id = ? ORDER BY id",
                (s["session_id"],),
            ).fetchall()
            s["turns"] = [dict(t) for t in turns]
            result.append(s)
        return result


def get_session_turns(session_id: str) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, text, timestamp FROM turns WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]
