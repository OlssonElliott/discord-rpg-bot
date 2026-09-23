"""Character lifecycle and selection persistence for the database facade."""

from __future__ import annotations

from collections.abc import Mapping
import sqlite3

from ..errors import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    InvalidHitPointsError,
)
from ...characters.models import Character, Stance
from ...media.portraits import default_portrait_key


class DatabaseCharactersMixin:
    """Persist character creation, selection, identity, and archival."""

    def create_character(
        self,
        discord_user_id: int,
        name: str,
        max_hp: int,
        *,
        lineage: str | None = None,
        race: str | None = None,
        age: str | None = None,
        gender: str | None = None,
        attributes: Mapping[str, int] | None = None,
        skills: Mapping[str, int] | None = None,
        portrait_key: str | None = None,
    ) -> Character:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Character name cannot be empty.")
        if len(clean_name) > 100:
            raise ValueError("Character name cannot be longer than 100 characters.")
        if max_hp <= 0:
            raise InvalidHitPointsError("Maximum HP must be greater than 0.")
        if portrait_key is None:
            portrait_key = default_portrait_key(race, gender)

        try:
            with self._connect() as connection:
                previous = connection.execute(
                    """
                    SELECT id FROM characters
                    WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                    """,
                    (discord_user_id,),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE characters SET is_active = 0
                    WHERE discord_user_id = ? AND is_archived = 0
                    """,
                    (discord_user_id,),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO characters (
                        discord_user_id, name, hp, max_hp, stance,
                        lineage, race, age, gender,
                        strength, dexterity, arcana, vitality, insight, personality,
                        portrait_key, is_active, is_archived
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (
                        discord_user_id,
                        clean_name,
                        max_hp,
                        max_hp,
                        Stance.STEADY.value,
                        lineage,
                        race,
                        age,
                        gender,
                        *((attributes or {}).get(attribute) for attribute in (
                            "Strength",
                            "Dexterity",
                            "Arcana",
                            "Vitality",
                            "Insight",
                            "Personality",
                        )),
                        portrait_key,
                    ),
                )
                character_id = cursor.lastrowid
                connection.execute(
                    """
                    INSERT INTO character_combat_states (
                        character_id, status, failed_death_saves
                    ) VALUES (?, 'active', 0)
                    """,
                    (character_id,),
                )
                if previous is not None:
                    self._transfer_private_views(
                        connection, previous["id"], character_id
                    )
                else:
                    self._claim_private_views(
                        connection, discord_user_id, character_id
                    )
                connection.executemany(
                    """
                    INSERT INTO character_skills (character_id, skill, rank)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (character_id, skill, rank)
                        for skill, rank in (skills or {}).items()
                    ),
                )
                self._ensure_default_clothing(connection, character_id)
        except sqlite3.IntegrityError as error:
            raise CharacterAlreadyExistsError(
                "You already have a selectable character with that name."
            ) from error

        character = self.get_character_by_id(discord_user_id, character_id)
        if character is None:
            raise RuntimeError("Newly created character could not be loaded.")
        return character

    def select_character(self, discord_user_id: int, character_id: int) -> Character:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM characters
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (character_id, discord_user_id),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character is not selectable.")
            previous = connection.execute(
                """
                SELECT id FROM characters
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (discord_user_id,),
            ).fetchone()
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE discord_user_id = ?",
                (discord_user_id,),
            )
            connection.execute(
                "UPDATE characters SET is_active = 1 WHERE id = ?",
                (character_id,),
            )
            if previous is not None and previous["id"] != character_id:
                self._transfer_private_views(
                    connection, previous["id"], character_id
                )
            elif previous is None:
                self._claim_private_views(
                    connection, discord_user_id, character_id
                )
        character = self.get_character(discord_user_id)
        if character is None:
            raise RuntimeError("Selected character could not be loaded.")
        return character

    def deactivate_character(self, discord_user_id: int) -> None:
        """Leave a Discord user without an equipped/active character."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE characters SET is_active = 0
                WHERE discord_user_id = ? AND is_archived = 0
                """,
                (discord_user_id,),
            )

    def set_character_portrait(
        self, discord_user_id: int, character_id: int, portrait_key: str | None
    ) -> Character:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE characters SET portrait_key = ?
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (portrait_key, character_id, discord_user_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That character is not selectable.")
        character = self.get_character_by_id(discord_user_id, character_id)
        if character is None:
            raise RuntimeError("Updated character could not be loaded.")
        return character

    def archive_character(self, discord_user_id: int, character_id: int) -> Character:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, is_active FROM characters
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (character_id, discord_user_id),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character is not selectable.")
            connection.execute(
                "UPDATE characters SET is_active = 0, is_archived = 1 WHERE id = ?",
                (character_id,),
            )
            if row["is_active"]:
                replacement = connection.execute(
                    """
                    SELECT id FROM characters
                    WHERE discord_user_id = ? AND is_archived = 0
                    ORDER BY id DESC LIMIT 1
                    """,
                    (discord_user_id,),
                ).fetchone()
                if replacement is not None:
                    connection.execute(
                        "UPDATE characters SET is_active = 1 WHERE id = ?",
                        (replacement["id"],),
                    )
                    self._transfer_private_views(
                        connection, character_id, replacement["id"]
                    )
        archived = self.get_character_by_id(
            discord_user_id, character_id, include_archived=True
        )
        if archived is None:
            raise RuntimeError("Archived character could not be loaded.")
        return archived

