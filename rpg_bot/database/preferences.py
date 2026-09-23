"""User preference persistence mixed into the main database facade."""

from __future__ import annotations

from ..dice.visuals import (
    DEFAULT_DICE_COLOR,
    DEFAULT_DICE_EDGE_COLOR,
    DEFAULT_DICE_NUMBER_COLOR,
    normalize_dice_color,
)


class DatabasePreferencesMixin:
    """Persist user-facing dice and Dungeon Master appearance preferences."""

    def get_dice_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dice_color"] if row else DEFAULT_DICE_COLOR

    def get_dm_portrait(self, discord_user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dm_portrait_key
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dm_portrait_key"] if row else None

    def set_dm_portrait(
        self,
        discord_user_id: int,
        portrait_key: str | None,
    ) -> str | None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (
                    discord_user_id, dice_color, dm_portrait_key
                )
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dm_portrait_key = excluded.dm_portrait_key
                """,
                (discord_user_id, DEFAULT_DICE_COLOR, portrait_key),
            )
        return portrait_key

    def set_dice_color(
        self,
        discord_user_id: int,
        color: str,
    ) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (discord_user_id, dice_color)
                VALUES (?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_color = excluded.dice_color
                """,
                (discord_user_id, normalized_color),
            )
        return normalized_color

    def get_dice_edge_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_edge_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dice_edge_color"] if row else DEFAULT_DICE_EDGE_COLOR

    def set_dice_edge_color(
        self,
        discord_user_id: int,
        color: str,
    ) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (
                    discord_user_id,
                    dice_color,
                    dice_edge_color
                )
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_edge_color = excluded.dice_edge_color
                """,
                (
                    discord_user_id,
                    DEFAULT_DICE_COLOR,
                    normalized_color,
                ),
            )
        return normalized_color

    def get_dice_number_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_number_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return (
            row["dice_number_color"]
            if row
            else DEFAULT_DICE_NUMBER_COLOR
        )

    def set_dice_number_color(
        self,
        discord_user_id: int,
        color: str,
    ) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (
                    discord_user_id,
                    dice_color,
                    dice_number_color
                )
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_number_color = excluded.dice_number_color
                """,
                (
                    discord_user_id,
                    DEFAULT_DICE_COLOR,
                    normalized_color,
                ),
            )
        return normalized_color
