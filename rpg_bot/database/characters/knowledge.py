"""Character world-knowledge persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from ..errors import CharacterNotFoundError
from ...world.dungeon import (
    CharacterRoomKnowledge,
    ConnectionType,
    KnowledgeSource,
    KnowledgeState,
    RoomConnection,
    TrapDamageType,
    TrapState,
)


class DatabaseCharacterKnowledgeMixin:
    """Persist discovered rooms, exits, and shared character knowledge."""

    def ensure_character_location_knowledge(self, character_id: int) -> None:
        """Ensure the current room and its presently visible exits are known."""
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT current_room_id FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            room_id = character["current_room_id"]
            if room_id is None:
                return
            known = connection.execute(
                """
                SELECT 1 FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (character_id, room_id),
            ).fetchone()
            if known is None:
                self._record_room_visit(connection, character_id, room_id)
            else:
                self._record_visible_connections(
                    connection, character_id, room_id
                )

    def get_character_knowledge(
        self, character_id: int, room_id: str
    ) -> CharacterRoomKnowledge | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT character_id, room_id, state, source, first_visited_at,
                       last_visited_at, last_seen_scene_id, shared_by_character_id
                FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (character_id, room_id),
            ).fetchone()
            if row is None:
                return None
            connection_ids = tuple(
                item["connection_id"]
                for item in connection.execute(
                    """
                    SELECT connection_id FROM character_known_connections
                    WHERE character_id = ? ORDER BY connection_id
                    """,
                    (character_id,),
                )
                if connection.execute(
                    """
                    SELECT 1 FROM room_connections
                    WHERE id = ? AND (from_room_id = ? OR to_room_id = ?)
                    """,
                    (item["connection_id"], room_id, room_id),
                ).fetchone()
            )
            return self._to_knowledge(row, connection_ids)

    def list_character_knowledge(
        self, character_id: int, *, floor_id: str | None = None
    ) -> tuple[CharacterRoomKnowledge, ...]:
        with self._connect() as connection:
            parameters: list[object] = [character_id]
            floor_clause = ""
            if floor_id is not None:
                floor_clause = " AND rooms.floor_id = ?"
                parameters.append(floor_id)
            rows = connection.execute(
                """
                SELECT k.character_id, k.room_id, k.state, k.source,
                       k.first_visited_at, k.last_visited_at, k.last_seen_scene_id,
                       k.shared_by_character_id
                FROM character_room_knowledge AS k
                JOIN rooms ON rooms.id = k.room_id
                WHERE k.character_id = ?
                """ + floor_clause + " ORDER BY k.room_id",
                parameters,
            ).fetchall()
            known_connections = {
                item["connection_id"]
                for item in connection.execute(
                    """
                    SELECT connection_id FROM character_known_connections
                    WHERE character_id = ?
                    """,
                    (character_id,),
                )
            }
            result = []
            for row in rows:
                room_connection_ids = tuple(
                    item["id"]
                    for item in connection.execute(
                        """
                        SELECT id FROM room_connections
                        WHERE from_room_id = ? OR to_room_id = ? ORDER BY id
                        """,
                        (row["room_id"], row["room_id"]),
                    )
                    if item["id"] in known_connections
                )
                result.append(self._to_knowledge(row, room_connection_ids))
            return tuple(result)

    def share_room_knowledge(
        self, from_character_id: int, to_character_id: int, room_id: str
    ) -> CharacterRoomKnowledge:
        if from_character_id == to_character_id:
            raise ValueError("A character cannot share room knowledge with itself.")
        with self._connect() as connection:
            source = connection.execute(
                """
                SELECT 1 FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (from_character_id, room_id),
            ).fetchone()
            if source is None:
                raise ValueError("The sharing character does not know that room.")
            if connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (to_character_id,),
            ).fetchone() is None:
                raise CharacterNotFoundError("The receiving character does not exist.")
            connection.execute(
                """
                INSERT INTO character_room_knowledge (
                    character_id, room_id, state, source, shared_by_character_id
                ) VALUES (?, ?, 'known', 'shared', ?)
                ON CONFLICT(character_id, room_id) DO NOTHING
                """,
                (to_character_id, room_id, from_character_id),
            )
        knowledge = self.get_character_knowledge(to_character_id, room_id)
        assert knowledge is not None
        return knowledge

    def list_known_connections(self, character_id: int) -> tuple[RoomConnection, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.from_room_id, c.to_room_id, c.connection_type,
                       c.hidden, c.bidirectional, c.has_lock, c.is_locked,
                       c.unlock_difficulty, c.is_broken, c.is_open, c.has_trap,
                       c.trap_state, c.trap_detection_difficulty,
                       c.trap_disarm_difficulty,
                       c.trap_damage_type,
                       c.trap_damage
                FROM room_connections AS c
                JOIN character_known_connections AS known
                  ON known.connection_id = c.id
                WHERE known.character_id = ? AND c.hidden = 0
                ORDER BY c.id
                """,
                (character_id,),
            ).fetchall()
        return tuple(
            RoomConnection(
                row["id"], row["from_room_id"], row["to_room_id"],
                ConnectionType(row["connection_type"]), bool(row["hidden"]),
                bool(row["bidirectional"]),
                bool(row["has_lock"]),
                bool(row["is_locked"]), row["unlock_difficulty"],
                bool(row["is_broken"]),
                bool(row["is_open"]),
                bool(row["has_trap"]),
                (
                    TrapState(row["trap_state"])
                    if row["trap_state"] is not None
                    else None
                ),
                row["trap_detection_difficulty"],
                row["trap_disarm_difficulty"],
                (
                    TrapDamageType(row["trap_damage_type"])
                    if row["trap_damage_type"] is not None
                    else None
                ),
                row["trap_damage"],
            )
            for row in rows
        )

    @staticmethod
    def _record_room_visit(
        connection: sqlite3.Connection, character_id: int, room_id: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO character_room_knowledge (
                character_id, room_id, state, source, first_visited_at, last_visited_at
            ) VALUES (?, ?, 'visited', 'discovered', ?, ?)
            ON CONFLICT(character_id, room_id) DO UPDATE SET
                state = 'visited',
                source = 'discovered',
                first_visited_at = COALESCE(
                    character_room_knowledge.first_visited_at, excluded.first_visited_at
                ),
                last_visited_at = excluded.last_visited_at,
                shared_by_character_id = NULL
            """,
            (character_id, room_id, now, now),
        )
        connection.execute(
            """
            UPDATE player_view_states
            SET selected_floor_id = (SELECT floor_id FROM rooms WHERE id = ?),
                focused_room_id = ?
            WHERE character_id = ?
            """,
            (room_id, room_id, character_id),
        )
        DatabaseCharacterKnowledgeMixin._record_visible_connections(
            connection, character_id, room_id
        )

    @staticmethod
    def _record_visible_connections(
        connection: sqlite3.Connection, character_id: int, room_id: str
    ) -> None:
        """Reveal every currently visible exit from a character's room."""
        connection_rows = connection.execute(
            """
                SELECT id, from_room_id, to_room_id, bidirectional,
                       connection_type, is_open
            FROM room_connections
            WHERE hidden = 0 AND (
                from_room_id = ? OR (to_room_id = ? AND bidirectional = 1)
            )
            """,
            (room_id, room_id),
        ).fetchall()
        for connection_row in connection_rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO character_known_connections (
                    character_id, connection_id
                ) VALUES (?, ?)
                """,
                (character_id, connection_row["id"]),
            )
            adjacent_room_id = (
                connection_row["to_room_id"]
                if connection_row["from_room_id"] == room_id
                else connection_row["from_room_id"]
            )
            if (
                ConnectionType(connection_row["connection_type"])
                is ConnectionType.DOOR
                and not connection_row["is_open"]
            ):
                continue
            connection.execute(
                """
                INSERT INTO character_room_knowledge (
                    character_id, room_id, state, source
                ) VALUES (?, ?, 'known', 'discovered')
                ON CONFLICT(character_id, room_id) DO NOTHING
                """,
                (character_id, adjacent_room_id),
            )

    @staticmethod
    def _to_knowledge(
        row: sqlite3.Row, connection_ids: tuple[str, ...]
    ) -> CharacterRoomKnowledge:
        def parsed(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return CharacterRoomKnowledge(
            row["character_id"],
            row["room_id"],
            KnowledgeState(row["state"]),
            KnowledgeSource(row["source"]),
            connection_ids,
            parsed(row["first_visited_at"]),
            parsed(row["last_visited_at"]),
            row["last_seen_scene_id"],
            row["shared_by_character_id"],
        )
