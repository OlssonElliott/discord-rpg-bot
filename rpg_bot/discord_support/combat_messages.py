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
    turn_marker_id: int = 0


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
                    message_id INTEGER NOT NULL,
                    turn_marker_id INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            fields = {
                row["name"] for row in db.execute(
                    "PRAGMA table_info(combat_discord_messages)"
                )
            }
            if "turn_marker_id" not in fields:
                db.execute(
                    "ALTER TABLE combat_discord_messages ADD COLUMN "
                    "turn_marker_id INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS combat_discord_turn_messages (
                    scene_id INTEGER NOT NULL,
                    start_marker_id INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY (scene_id, start_marker_id, page_number)
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
                "SELECT guild_id, scene_id, channel_id, message_id, turn_marker_id "
                "FROM combat_discord_messages WHERE guild_id = ?",
                (guild_id,),
            ).fetchone()
        return CombatMessage(**dict(row)) if row is not None else None

    def save(
        self,
        guild_id: int,
        scene_id: int,
        channel_id: int,
        message_id: int,
        turn_marker_id: int = 0,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO combat_discord_messages
                    (guild_id, scene_id, channel_id, message_id, turn_marker_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    scene_id = excluded.scene_id,
                    channel_id = excluded.channel_id,
                    message_id = excluded.message_id,
                    turn_marker_id = excluded.turn_marker_id
                """,
                (guild_id, scene_id, channel_id, message_id, turn_marker_id),
            )

    def get_turn_page(
        self, scene_id: int, start_marker_id: int, page_number: int,
    ) -> tuple[int, int] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT channel_id, message_id FROM combat_discord_turn_messages "
                "WHERE scene_id=? AND start_marker_id=? AND page_number=?",
                (scene_id, start_marker_id, page_number),
            ).fetchone()
        return (int(row["channel_id"]), int(row["message_id"])) if row else None

    def save_turn_page(
        self, scene_id: int, start_marker_id: int, page_number: int,
        channel_id: int, message_id: int,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO combat_discord_turn_messages
                    (scene_id,start_marker_id,page_number,channel_id,message_id)
                VALUES (?,?,?,?,?)
                """,
                (scene_id,start_marker_id,page_number,channel_id,message_id),
            )

    def clear(self, guild_id: int) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM combat_discord_messages WHERE guild_id = ?",
                (guild_id,),
            )
