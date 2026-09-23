"""Ownership transfer for player-owned private Discord views."""

from __future__ import annotations

import sqlite3

from .characters.sheet import DatabaseCharacterSheetMixin


class DatabasePrivateViewsMixin:
    """Move player-owned map and character-sheet bindings between characters."""

    @staticmethod
    def _transfer_private_views(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        """Move player-owned Discord HUD bindings while preserving knowledge."""
        DatabasePrivateViewsMixin._transfer_map_view(
            connection, previous_character_id, new_character_id
        )
        DatabaseCharacterSheetMixin._transfer_sheet_view(
            connection, previous_character_id, new_character_id
        )

    @staticmethod
    def _claim_private_views(
        connection: sqlite3.Connection,
        discord_user_id: int,
        new_character_id: int,
    ) -> None:
        map_owner = connection.execute(
            """
            SELECT state.character_id FROM player_view_states AS state
            JOIN characters ON characters.id = state.character_id
            WHERE characters.discord_user_id = ? AND state.character_id != ?
            ORDER BY state.character_id DESC LIMIT 1
            """,
            (discord_user_id, new_character_id),
        ).fetchone()
        if map_owner is not None:
            DatabasePrivateViewsMixin._transfer_map_view(
                connection, map_owner["character_id"], new_character_id
            )
        sheet_owner = connection.execute(
            """
            SELECT state.character_id FROM character_sheet_view_states AS state
            JOIN characters ON characters.id = state.character_id
            WHERE characters.discord_user_id = ? AND state.character_id != ?
            ORDER BY state.character_id DESC LIMIT 1
            """,
            (discord_user_id, new_character_id),
        ).fetchone()
        if sheet_owner is not None:
            DatabaseCharacterSheetMixin._transfer_sheet_view(
                connection, sheet_owner["character_id"], new_character_id
            )

    @staticmethod
    def _transfer_map_view(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        previous_map = connection.execute(
            "SELECT * FROM player_view_states WHERE character_id = ?",
            (previous_character_id,),
        ).fetchone()
        if previous_map is not None:
            connection.execute(
                "DELETE FROM player_view_states WHERE character_id = ?",
                (new_character_id,),
            )
            room = connection.execute(
                """
                SELECT rooms.id, rooms.floor_id FROM characters
                LEFT JOIN rooms ON rooms.id = characters.current_room_id
                WHERE characters.id = ?
                """,
                (new_character_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE player_view_states
                SET character_id = ?, selected_floor_id = ?, focused_room_id = ?
                WHERE character_id = ?
                """,
                (
                    new_character_id,
                    room["floor_id"] if room else None,
                    room["id"] if room else None,
                    previous_character_id,
                ),
            )
