"""Persistent Discord message pointer for the shared combat scene.

The combat scene itself always lives in CombatService / SQLite. This table
only remembers which public Discord message presents it across bot restarts.
"""

from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class CombatMessage:
    guild_id: int
    scene_id: int
    channel_id: int
    message_id: int


class CombatMessageStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS combat_discord_messages (
                    guild_id INTEGER PRIMARY KEY,
                    scene_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, guild_id: int) -> CombatMessage | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT guild_id, scene_id, channel_id, message_id "
                "FROM combat_discord_messages WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
        return CombatMessage(**dict(row)) if row is not None else None

    def save(self, guild_id: int, scene_id: int, channel_id: int, message_id: int) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO combat_discord_messages
                    (guild_id, scene_id, channel_id, message_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    scene_id = excluded.scene_id,
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id
                """,
                (guild_id, scene_id, channel_id, message_id),
            )

    def clear(self, guild_id: int) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM combat_discord_messages WHERE guild_id = ?",
                (guild_id,),
            )
