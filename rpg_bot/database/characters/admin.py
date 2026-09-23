"""DM-facing character administration persistence."""

from __future__ import annotations

from collections.abc import Mapping
import sqlite3

from ..errors import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    InvalidHitPointsError,
)
from ...inventory import EquipmentSlot
from ...characters.models import Character, CharacterCombatStatus, Stance


class DatabaseCharacterAdminMixin:
    """Persist explicit DM edits to characters and inventory items."""

    def update_character_admin(
        self,
        character_id: int,
        *,
        name: str,
        hp: int,
        max_hp: int,
        stance: Stance,
        lineage: str | None,
        race: str | None,
        age: str | None,
        gender: str | None,
        attributes: Mapping[str, int],
        skills: Mapping[str, int],
        status: CharacterCombatStatus,
        failed_death_saves: int,
        current_room_id: str | None,
        copper: int,
        silver: int,
        gold: int,
    ) -> Character:
        """Apply an explicit DM edit to a character and its attached state."""
        clean_name = self._clean_name(name, "Character name")
        if max_hp <= 0:
            raise InvalidHitPointsError("Maximum HP must be greater than 0.")
        if not -max_hp <= hp <= max_hp:
            raise InvalidHitPointsError(
                f"HP must be between {-max_hp} and {max_hp}."
            )
        if not 0 <= failed_death_saves <= 3:
            raise ValueError("Failed death saves must be between 0 and 3.")
        if copper < 0 or silver < 0 or gold < 0:
            raise ValueError("Currency amounts cannot be negative.")

        attribute_names = (
            "Strength",
            "Dexterity",
            "Arcana",
            "Vitality",
            "Insight",
            "Personality",
        )
        normalized_attributes: dict[str, int | None] = {}
        for attribute in attribute_names:
            value = attributes.get(attribute)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{attribute} must be an integer.")
            normalized_attributes[attribute] = value

        normalized_skills: dict[str, int] = {}
        for skill, rank in skills.items():
            clean_skill = skill.strip()
            if not clean_skill:
                raise ValueError("Skill names cannot be empty.")
            if len(clean_skill) > 100:
                raise ValueError("Skill names cannot be longer than 100 characters.")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
                raise ValueError("Skill ranks must be non-negative integers.")
            if rank:
                normalized_skills[clean_skill] = rank

        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT current_room_id FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if current is None:
                raise CharacterNotFoundError("That character does not exist.")
            if current_room_id is not None:
                self._require_room(connection, current_room_id)

            try:
                connection.execute(
                    """
                    UPDATE characters
                    SET name = ?, hp = ?, max_hp = ?, stance = ?,
                        lineage = ?, race = ?, age = ?, gender = ?,
                        strength = ?, dexterity = ?, arcana = ?,
                        vitality = ?, insight = ?, personality = ?,
                        current_room_id = ?
                    WHERE id = ? AND is_archived = 0
                    """,
                    (
                        clean_name,
                        hp,
                        max_hp,
                        stance.value,
                        lineage,
                        race,
                        age,
                        gender,
                        normalized_attributes["Strength"],
                        normalized_attributes["Dexterity"],
                        normalized_attributes["Arcana"],
                        normalized_attributes["Vitality"],
                        normalized_attributes["Insight"],
                        normalized_attributes["Personality"],
                        current_room_id,
                        character_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise CharacterAlreadyExistsError(
                    "That Discord user already has a selectable character with this name."
                ) from error

            connection.execute(
                "DELETE FROM character_skills WHERE character_id = ?",
                (character_id,),
            )
            connection.executemany(
                """
                INSERT INTO character_skills (character_id, skill, rank)
                VALUES (?, ?, ?)
                """,
                (
                    (character_id, skill, rank)
                    for skill, rank in normalized_skills.items()
                ),
            )

            self._ensure_character_combat_state_row(connection, character_id)
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (status.value, failed_death_saves, character_id),
            )

            connection.execute(
                "INSERT OR IGNORE INTO character_wallets (character_id) VALUES (?)",
                (character_id,),
            )
            connection.execute(
                """
                UPDATE character_wallets
                SET copper = ?, silver = ?, gold = ?
                WHERE character_id = ?
                """,
                (copper, silver, gold, character_id),
            )

            previous_room_id = current["current_room_id"]
            if previous_room_id != current_room_id:
                if previous_room_id is not None:
                    self._queue_map_refresh_for_room(
                        connection,
                        previous_room_id,
                    )
                if current_room_id is not None:
                    self._record_room_visit(
                        connection,
                        character_id,
                        current_room_id,
                    )
                    self._queue_map_refresh_for_room(
                        connection,
                        current_room_id,
                    )

        updated = self.get_character_by_global_id(character_id)
        if updated is None:
            raise RuntimeError("Updated character could not be loaded.")
        return updated

    def set_character_inventory_item_admin(
        self,
        character_id: int,
        instance_id: str,
        *,
        quantity: int,
        durability: int | None,
        equipped_slot: EquipmentSlot | None,
    ) -> None:
        """Update one inventory instance from the local DM workspace."""
        if durability is not None and durability < 0:
            raise ValueError("Durability cannot be negative.")
        with self._connect() as connection:
            item = connection.execute(
                """
                SELECT 1 FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            ).fetchone()
            if item is None:
                raise ValueError("That item is not in this inventory.")

            connection.execute(
                """
                DELETE FROM character_equipment
                WHERE character_id = ? AND item_instance_id = ?
                """,
                (character_id, instance_id),
            )
            if quantity <= 0:
                connection.execute(
                    """
                    DELETE FROM character_items
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (character_id, instance_id),
                )
                return

            connection.execute(
                """
                UPDATE character_items
                SET quantity = ?, durability = ?, parent_container_id = NULL
                WHERE character_id = ? AND instance_id = ?
                """,
                (quantity, durability, character_id, instance_id),
            )
            if equipped_slot is not None:
                connection.execute(
                    """
                    DELETE FROM character_equipment
                    WHERE character_id = ? AND slot = ?
                    """,
                    (character_id, equipped_slot.value),
                )
                connection.execute(
                    """
                    INSERT INTO character_equipment (
                        character_id, slot, item_instance_id
                    ) VALUES (?, ?, ?)
                    """,
                    (character_id, equipped_slot.value, instance_id),
                )
