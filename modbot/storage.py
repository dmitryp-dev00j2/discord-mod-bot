import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rule_name TEXT NOT NULL,
    detail TEXT,
    action_taken TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    entry_id INTEGER UNIQUE NOT NULL,
    user_id INTEGER,
    target_id INTEGER,
    action_type INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_guild_user ON incidents (guild_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_guild ON audit_logs (guild_id, created_at);
"""


class ModStorage:
    """Handles persistence for infractions and mirrored audit logs."""

    def __init__(self, db_path: str = "modbot.db"):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def log_incident(self, guild_id: int, user_id: int, rule_name: str, detail: str, action: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            # print(f"DEBUG: logging incident {rule_name} for {user_id}")
            conn.execute(
                "INSERT INTO incidents (guild_id, user_id, rule_name, detail, action_taken, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, rule_name, detail, action, now),
            )
            conn.commit()

    def log_audit_entry(
        self,
        guild_id: int,
        entry_id: int,
        user_id: Optional[int],
        target_id: Optional[int],
        action_type: int,
        reason: Optional[str],
        created_at: Optional[datetime] = None,
    ):
        ts = created_at.isoformat() if created_at else datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO audit_logs (guild_id, entry_id, user_id, target_id, action_type, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, entry_id, user_id, target_id, action_type, reason or "", ts),
            )
            conn.commit()

    def get_user_incidents(self, guild_id: int, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM incidents WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, user_id, limit),
            )
            return [dict(row) for row in cur.fetchall()]

    def count_recent_incidents(self, guild_id: int, user_id: int, since_iso: str) -> int:
        # used for escalating punishments if repeated within short timeframes
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
                (guild_id, user_id, since_iso),
            )
            return cur.fetchone()[0]

    # TODO: add a prune job for entries older than 90 days
