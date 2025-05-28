import aiosqlite
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "trades.db"

class DB:
    def __init__(self):
        self._conn = None

    async def __aenter__(self):
        self._conn = await aiosqlite.connect(DB_PATH)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, side TEXT, qty REAL,
                price REAL, avg_price REAL, pnl REAL
            )
        """)
        await self._conn.commit()
        return self

    async def __aexit__(self, *_):
        await self._conn.close()

    async def log(self, side, qty, price, avg_price, pnl):
        await self._conn.execute(
            "INSERT INTO trades VALUES (NULL, ?, ?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), side, qty, price, avg_price, pnl)
        )
        await self._conn.commit()
