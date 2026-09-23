"""Character sheet view persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ...characters.models import CharacterSheetViewState


class DatabaseCharacterSheetMixin:
    """Persist Discord character-sheet messages and private HUD bindings."""

    @staticmethod
    def _transfer_sheet_view(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        previous_sheet = connection.execute(
            "SELECT 1 FROM character_sheet_view_states WHERE character_id = ?",
            (previous_character_id,),
        ).fetchone()
        if previous_sheet is not None:
            connection.execute(
                "DELETE FROM character_sheet_view_states WHERE character_id = ?",
                (new_character_id,),
            )
            connection.execute(
                """
                UPDATE character_sheet_view_states SET character_id = ?
                WHERE character_id = ?
                """,
                (new_character_id, previous_character_id),
            )

    def get_character_sheet_message(
        self, guild_id: int, channel_id: int, character_id: int
    ) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT message_id FROM character_sheet_messages
                WHERE guild_id = ? AND channel_id = ? AND character_id = ?
                """,
                (guild_id, channel_id, character_id),
            ).fetchone()
        return row["message_id"] if row else None

    def set_character_sheet_message(
        self,
        guild_id: int,
        channel_id: int,
        character_id: int,
        message_id: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_sheet_messages (
                    guild_id, channel_id, character_id, message_id
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (guild_id, channel_id, character_id)
                DO UPDATE SET message_id = excluded.message_id
                """,
                (guild_id, channel_id, character_id, message_id),
            )

    def get_character_sheet_view_state(
        self, character_id: int
    ) -> CharacterSheetViewState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT character_id, guild_id, discord_channel_id, discord_message_id
                FROM character_sheet_view_states WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()
        if row is None:
            return None
        return CharacterSheetViewState(
            row["character_id"], row["guild_id"], row["discord_channel_id"],
            row["discord_message_id"],
        )

    def bind_character_sheet_channel(
        self, character_id: int, guild_id: int, channel_id: int
    ) -> CharacterSheetViewState:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_sheet_view_states (
                    character_id, guild_id, discord_channel_id, discord_message_id
                ) VALUES (?, ?, ?, NULL)
                ON CONFLICT(character_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    discord_channel_id = excluded.discord_channel_id,
                    discord_message_id = CASE
                        WHEN character_sheet_view_states.guild_id = excluded.guild_id
                         AND character_sheet_view_states.discord_channel_id = excluded.discord_channel_id
                        THEN character_sheet_view_states.discord_message_id
                        ELSE NULL
                    END
                """,
                (character_id, guild_id, channel_id),
            )
        state = self.get_character_sheet_view_state(character_id)
        assert state is not None
        return state

    def set_character_sheet_view_message(
        self, character_id: int, message_id: int
    ) -> CharacterSheetViewState:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE character_sheet_view_states SET discord_message_id = ?
                WHERE character_id = ?
                """,
                (message_id, character_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("The character sheet channel is not configured.")
        state = self.get_character_sheet_view_state(character_id)
        assert state is not None
        return state

    def clear_character_sheet_view_state(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM character_sheet_view_states WHERE character_id = ?",
                (character_id,),
            )

    def list_character_sheet_view_states(
        self,
    ) -> tuple[CharacterSheetViewState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id, guild_id, discord_channel_id, discord_message_id
                FROM character_sheet_view_states ORDER BY character_id
                """
            ).fetchall()
        return tuple(
            CharacterSheetViewState(
                row["character_id"], row["guild_id"], row["discord_channel_id"],
                row["discord_message_id"],
            )
            for row in rows
        )
