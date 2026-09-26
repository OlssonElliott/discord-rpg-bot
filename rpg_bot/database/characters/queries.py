"""Character lookup and read-only persistence helpers."""

from __future__ import annotations

import sqlite3

from ..errors import CharacterNotFoundError
from ...characters.models import Character, Stance


class DatabaseCharacterQueriesMixin:
    """Read characters, attributes, skills, and persisted model state."""

    def get_character(self, discord_user_id: int) -> Character | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       hunger, is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (discord_user_id,),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def get_character_by_id(
        self,
        discord_user_id: int,
        character_id: int,
        *,
        include_archived: bool = False,
    ) -> Character | None:
        archived_clause = "" if include_archived else "AND is_archived = 0"
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       hunger, is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND id = ? {archived_clause}
                """,
                (discord_user_id, character_id),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def list_characters(self, discord_user_id: int) -> list[Character]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       hunger, is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND is_archived = 0
                ORDER BY is_active DESC, id ASC
                """,
                (discord_user_id,),
            ).fetchall()
            return [self._to_character_with_skills(connection, row) for row in rows]

    def list_all_characters(self) -> list[Character]:
        """Return every selectable character for DM-facing world tools."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       hunger, is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE is_archived = 0
                ORDER BY name COLLATE NOCASE, id ASC
                """
            ).fetchall()
            return [self._to_character_with_skills(connection, row) for row in rows]

    def get_character_by_global_id(self, character_id: int) -> Character | None:
        """Return one selectable character without requiring its Discord owner id."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       hunger, is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def get_character_skill_rank(self, character_id: int, skill: str) -> int:
        """Return a case-insensitive skill-tree rank, or zero if it is unknown."""
        normalized = skill.strip()
        if not normalized:
            return 0
        with self._connect() as connection:
            row = connection.execute(
                "SELECT rank FROM character_skills "
                "WHERE character_id = ? AND skill = ? COLLATE NOCASE",
                (character_id, normalized),
            ).fetchone()
        return int(row["rank"]) if row is not None else 0

    def get_character_attribute(self, character_id: int, attribute: str) -> int:
        """Return a persisted character attribute, defaulting an unset score to 10."""
        normalized = attribute.casefold().strip()
        allowed_attributes = {
            "strength",
            "dexterity",
            "arcana",
            "vitality",
            "insight",
            "personality",
        }
        if normalized not in allowed_attributes:
            raise ValueError(f"Unknown character attribute '{attribute}'.")

        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {normalized} FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
        if row is None:
            raise CharacterNotFoundError(f"Character {character_id} does not exist.")
        value = row[normalized]
        return int(value) if value is not None else 10

    def _require_character(self, discord_user_id: int) -> Character:
        character = self.get_character(discord_user_id)
        if character is None:
            raise CharacterNotFoundError("That Discord user does not have a character.")
        return character

    @staticmethod
    def _to_character_with_skills(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Character:
        skill_rows = connection.execute(
            """
            SELECT skill, rank FROM character_skills
            WHERE character_id = ? ORDER BY skill
            """,
            (row["id"],),
        ).fetchall()
        return DatabaseCharacterQueriesMixin._to_character(row, skill_rows)

    @staticmethod
    def _to_character(
        row: sqlite3.Row, skill_rows: list[sqlite3.Row] | None = None
    ) -> Character:
        attribute_columns = {
            "Strength": "strength",
            "Dexterity": "dexterity",
            "Arcana": "arcana",
            "Vitality": "vitality",
            "Insight": "insight",
            "Personality": "personality",
        }
        return Character(
            discord_user_id=row["discord_user_id"],
            name=row["name"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            stance=Stance(row["stance"]),
            lineage=row["lineage"],
            race=row["race"],
            age=row["age"],
            gender=row["gender"],
            hunger=int(row["hunger"]),
            attributes={
                attribute: row[column]
                for attribute, column in attribute_columns.items()
                if row[column] is not None
            },
            skills={
                skill_row["skill"]: skill_row["rank"]
                for skill_row in (skill_rows or [])
            },
            character_id=row["id"],
            is_active=bool(row["is_active"]),
            is_archived=bool(row["is_archived"]),
            portrait_key=row["portrait_key"],
            current_room_id=row["current_room_id"],
        )
