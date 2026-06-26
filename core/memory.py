import aiosqlite
import json
import asyncio
from datetime import datetime
from pathlib import Path
from config.settings import settings


class MemoryManager:
    def __init__(self):
        self.db_path = settings.MEMORY_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS short_term (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS long_term (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(category, key)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                description TEXT NOT NULL,
                metadata TEXT,
                timestamp TEXT NOT NULL
            );
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    async def add_message(self, role: str, content: str):
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "INSERT INTO short_term (role, content, timestamp) VALUES (?, ?, ?)",
            (role, content, now)
        )
        await self._db.commit()
        await self._trim_short_term()

    async def _trim_short_term(self):
        await self._db.execute("""
            DELETE FROM short_term WHERE id NOT IN (
                SELECT id FROM short_term ORDER BY id DESC LIMIT ?
            )
        """, (settings.MAX_SHORT_TERM_MESSAGES,))
        await self._db.commit()

    async def get_recent_messages(self, limit: int = None) -> list[dict]:
        n = limit or settings.MAX_SHORT_TERM_MESSAGES
        async with self._db.execute(
            "SELECT role, content FROM short_term ORDER BY id DESC LIMIT ?", (n,)
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

    async def remember(self, category: str, key: str, value: str):
        now = datetime.utcnow().isoformat()
        await self._db.execute("""
            INSERT INTO long_term (category, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """, (category, key, value, now))
        await self._db.commit()

    async def recall(self, category: str, key: str) -> str | None:
        async with self._db.execute(
            "SELECT value FROM long_term WHERE category=? AND key=?", (category, key)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else None

    async def recall_category(self, category: str) -> dict:
        async with self._db.execute(
            "SELECT key, value FROM long_term WHERE category=?", (category,)
        ) as cursor:
            rows = await cursor.fetchall()
        return {r[0]: r[1] for r in rows}

    async def log_event(self, event_type: str, description: str, metadata: dict = None):
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            "INSERT INTO events (event_type, description, metadata, timestamp) VALUES (?, ?, ?, ?)",
            (event_type, description, json.dumps(metadata) if metadata else None, now)
        )
        await self._db.commit()

    async def get_recent_events(self, event_type: str = None, limit: int = 10) -> list[dict]:
        if event_type:
            query = "SELECT event_type, description, metadata, timestamp FROM events WHERE event_type=? ORDER BY id DESC LIMIT ?"
            args = (event_type, limit)
        else:
            query = "SELECT event_type, description, metadata, timestamp FROM events ORDER BY id DESC LIMIT ?"
            args = (limit,)
        async with self._db.execute(query, args) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "type": r[0],
                "description": r[1],
                "metadata": json.loads(r[2]) if r[2] else None,
                "timestamp": r[3]
            }
            for r in rows
        ]
