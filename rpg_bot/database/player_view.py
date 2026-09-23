"""Player view and game-state persistence for the database facade."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from .errors import CharacterNotFoundError
from ..world.dungeon import GameLock, PlayerViewState


class DatabasePlayerViewMixin:
    """Persist player map view state, refresh requests, and game lock state."""

    def get_player_view_state(self, character_id: int) -> PlayerViewState:
        with self._connect() as connection:
            character = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            row = connection.execute(
                """
                SELECT character_id, selected_floor_id, focused_room_id,
                       discord_channel_id, discord_message_id
                FROM player_view_states WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()
            if row is None:
                room = connection.execute(
                    "SELECT floor_id FROM rooms WHERE id = ?",
                    (character["current_room_id"],),
                ).fetchone()
                selected_floor_id = room["floor_id"] if room else None
                connection.execute(
                    """
                    INSERT INTO player_view_states (
                        character_id, selected_floor_id, focused_room_id
                    ) VALUES (?, ?, ?)
                    """,
                    (character_id, selected_floor_id, character["current_room_id"]),
                )
                return PlayerViewState(
                    character_id, selected_floor_id, character["current_room_id"]
                )
            return PlayerViewState(
                row["character_id"], row["selected_floor_id"], row["focused_room_id"],
                row["discord_channel_id"], row["discord_message_id"],
            )

    def update_player_view_state(
        self,
        character_id: int,
        *,
        selected_floor_id: str | None = None,
        focused_room_id: str | None = None,
        discord_channel_id: int | None = None,
        discord_message_id: int | None = None,
    ) -> PlayerViewState:
        current = self.get_player_view_state(character_id)
        values = PlayerViewState(
            character_id,
            selected_floor_id if selected_floor_id is not None else current.selected_floor_id,
            focused_room_id if focused_room_id is not None else current.focused_room_id,
            discord_channel_id if discord_channel_id is not None else current.discord_channel_id,
            discord_message_id if discord_message_id is not None else current.discord_message_id,
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states SET selected_floor_id = ?, focused_room_id = ?,
                    discord_channel_id = ?, discord_message_id = ?
                WHERE character_id = ?
                """,
                (
                    values.selected_floor_id, values.focused_room_id,
                    values.discord_channel_id, values.discord_message_id, character_id,
                ),
            )
        return values

    def bind_player_view_channel(
        self, character_id: int, channel_id: int
    ) -> PlayerViewState:
        self.get_player_view_state(character_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states
                SET discord_channel_id = ?, discord_message_id = NULL
                WHERE character_id = ?
                """,
                (channel_id, character_id),
            )
        return self.get_player_view_state(character_id)

    def clear_player_view_channel(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states
                SET discord_channel_id = NULL, discord_message_id = NULL
                WHERE character_id = ?
                """,
                (character_id,),
            )

    def list_player_view_states(self) -> tuple[PlayerViewState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id, selected_floor_id, focused_room_id,
                       discord_channel_id, discord_message_id
                FROM player_view_states ORDER BY character_id
                """
            ).fetchall()
        return tuple(
            PlayerViewState(
                row["character_id"], row["selected_floor_id"],
                row["focused_room_id"], row["discord_channel_id"],
                row["discord_message_id"],
            )
            for row in rows
        )

    def request_player_map_refresh(self, character_id: int) -> None:
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone() is None:
                raise CharacterNotFoundError("That character does not exist.")
            self._queue_player_map_refresh(connection, character_id)

    def pending_player_map_refreshes(self) -> tuple[int, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id FROM player_map_refresh_requests
                ORDER BY requested_at, character_id
                """
            ).fetchall()
        return tuple(row["character_id"] for row in rows)

    def clear_player_map_refresh(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM player_map_refresh_requests WHERE character_id = ?",
                (character_id,),
            )

    @staticmethod
    def _queue_player_map_refresh(
        connection: sqlite3.Connection, character_id: int
    ) -> None:
        connection.execute(
            """
            INSERT INTO player_map_refresh_requests (character_id, requested_at)
            VALUES (?, ?)
            ON CONFLICT(character_id) DO UPDATE SET requested_at = excluded.requested_at
            """,
            (character_id, datetime.now(timezone.utc).isoformat()),
        )

    @classmethod
    def _queue_map_refresh_for_room(
        cls,
        connection: sqlite3.Connection,
        room_id: str,
        *,
        include_focused: bool = False,
    ) -> None:
        rows = connection.execute(
            """
            SELECT characters.id
            FROM characters
            JOIN player_view_states
              ON player_view_states.character_id = characters.id
            WHERE (
                    characters.current_room_id = ?
                    OR (? = 1 AND player_view_states.focused_room_id = ?)
                  )
              AND characters.is_archived = 0
              AND player_view_states.discord_channel_id IS NOT NULL
            """,
            (room_id, int(include_focused), room_id),
        ).fetchall()
        for row in rows:
            cls._queue_player_map_refresh(connection, row["id"])

    def get_game_lock(self) -> GameLock:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT lock_state FROM game_state WHERE id = 1"
            ).fetchone()
        return GameLock(row["lock_state"])

    def set_game_lock(self, state: GameLock) -> GameLock:
        with self._connect() as connection:
            connection.execute(
                "UPDATE game_state SET lock_state = ? WHERE id = 1", (state.value,)
            )
        return state
