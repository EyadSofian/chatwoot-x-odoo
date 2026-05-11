from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_syncs (
                    conversation_id INTEGER PRIMARY KEY,
                    synced_at INTEGER NOT NULL
                )
                """
            )

    def mark_delivery_once(self, delivery_id: str | None) -> bool:
        if not delivery_id:
            return True
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO webhook_deliveries(delivery_id, created_at) VALUES (?, ?)",
                    (delivery_id, int(time.time())),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def should_sync_conversation(self, conversation_id: int, ttl_seconds: int) -> bool:
        now = int(time.time())
        with self._connect() as conn:
            row = conn.execute(
                "SELECT synced_at FROM conversation_syncs WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if not row:
            return True
        return now - int(row[0]) >= ttl_seconds

    def mark_conversation_synced(self, conversation_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_syncs(conversation_id, synced_at)
                VALUES (?, ?)
                ON CONFLICT(conversation_id)
                DO UPDATE SET synced_at = excluded.synced_at
                """,
                (conversation_id, int(time.time())),
            )

