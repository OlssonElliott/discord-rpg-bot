"""Character combat-state persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ..errors import CharacterNotFoundError, InvalidHitPointsError
from ...characters.models import (
    Character,
    CharacterCombatState,
    CharacterCombatStatus,
    Stance,
)


class DatabaseCharacterCombatMixin:
    """Persist character HP, combat status, death saves, and stance."""

    @staticmethod
    def _ensure_character_combat_state_row(
        connection: sqlite3.Connection,
        character_id: int,
    ) -> sqlite3.Row:
        character = connection.execute(
            """
            SELECT id, hp, max_hp FROM characters
            WHERE id = ? AND is_archived = 0
            """,
            (character_id,),
        ).fetchone()
        if character is None:
            raise CharacterNotFoundError(
                f"Character {character_id} does not exist."
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO character_combat_states (
                character_id, status, failed_death_saves
            ) VALUES (
                ?,
                CASE
                    WHEN ? <= -? THEN 'dead'
                    WHEN ? <= 0 THEN 'downed'
                    ELSE 'active'
                END,
                0
            )
            """,
            (
                character_id,
                character["hp"],
                character["max_hp"],
                character["hp"],
            ),
        )
        row = connection.execute(
            """
            SELECT character_id, status, failed_death_saves
            FROM character_combat_states
            WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        assert row is not None
        return row

    @staticmethod
    def _combat_state_from_row(row: sqlite3.Row) -> CharacterCombatState:
        return CharacterCombatState(
            character_id=int(row["character_id"]),
            status=CharacterCombatStatus(row["status"]),
            failed_death_saves=int(row["failed_death_saves"]),
        )

    def get_character_combat_state(
        self,
        character_id: int,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            row = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            return self._combat_state_from_row(row)

    @classmethod
    def _apply_character_damage(
        cls,
        connection: sqlite3.Connection,
        character_id: int,
        amount: int,
    ) -> tuple[int, int, CharacterCombatStatus]:
        character = connection.execute(
            """
            SELECT hp, max_hp FROM characters
            WHERE id = ? AND is_archived = 0
            """,
            (character_id,),
        ).fetchone()
        if character is None:
            raise CharacterNotFoundError(
                f"Character {character_id} does not exist."
            )
        state = cls._ensure_character_combat_state_row(
            connection,
            character_id,
        )
        old_hp = int(character["hp"])
        max_hp = int(character["max_hp"])
        new_hp = max(-max_hp, old_hp - amount)

        if new_hp <= -max_hp:
            new_status = CharacterCombatStatus.DEAD
        elif new_hp <= 0:
            new_status = CharacterCombatStatus.DOWNED
        elif state["status"] == CharacterCombatStatus.RECOVERING.value:
            new_status = CharacterCombatStatus.RECOVERING
        else:
            new_status = CharacterCombatStatus.ACTIVE

        failed_death_saves = int(state["failed_death_saves"])
        if old_hp > 0 and new_hp <= 0:
            failed_death_saves = 0

        connection.execute(
            "UPDATE characters SET hp = ? WHERE id = ?",
            (new_hp, character_id),
        )
        connection.execute(
            """
            UPDATE character_combat_states
            SET status = ?, failed_death_saves = ?
            WHERE character_id = ?
            """,
            (
                new_status.value,
                failed_death_saves,
                character_id,
            ),
        )
        return new_hp, max_hp, new_status

    def damage(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Damage must be greater than 0.")
        character = self._require_character(discord_user_id)
        assert character.character_id is not None
        return self.damage_character_by_id(character.character_id, amount)

    def damage_character_by_id(
        self,
        character_id: int,
        amount: int,
    ) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Damage must be greater than 0.")
        with self._connect() as connection:
            self._apply_character_damage(
                connection,
                character_id,
                amount,
            )
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
            assert row is not None
            return self._to_character_with_skills(connection, row)

    def heal(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Healing must be greater than 0.")
        character = self._require_character(discord_user_id)
        assert character.character_id is not None
        return self.heal_character_by_id(character.character_id, amount)

    def heal_character_by_id(
        self,
        character_id: int,
        amount: int,
    ) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Healing must be greater than 0.")
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT hp, max_hp FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError(
                    f"Character {character_id} does not exist."
                )
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            if state["status"] == CharacterCombatStatus.DEAD.value:
                raise InvalidHitPointsError(
                    "Dead characters cannot be restored by normal healing."
                )

            old_hp = int(character["hp"])
            max_hp = int(character["max_hp"])
            new_hp = min(max_hp, old_hp + amount)
            if old_hp <= 0 < new_hp:
                new_status = CharacterCombatStatus.RECOVERING
                failed_death_saves = 0
            else:
                new_status = CharacterCombatStatus(state["status"])
                failed_death_saves = int(state["failed_death_saves"])

            connection.execute(
                "UPDATE characters SET hp = ? WHERE id = ?",
                (new_hp, character_id),
            )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (
                    new_status.value,
                    failed_death_saves,
                    character_id,
                ),
            )
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
            assert row is not None
            return self._to_character_with_skills(connection, row)

    def record_death_save(
        self,
        character_id: int,
        *,
        success: bool,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            if state["status"] != CharacterCombatStatus.DOWNED.value:
                raise InvalidHitPointsError(
                    "Only a downed character can make a death save."
                )
            if success:
                status = CharacterCombatStatus.STABLE
                failures = 0
            else:
                failures = min(3, int(state["failed_death_saves"]) + 1)
                status = (
                    CharacterCombatStatus.DEAD
                    if failures >= 3
                    else CharacterCombatStatus.DOWNED
                )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (status.value, failures, character_id),
            )
            return CharacterCombatState(
                character_id,
                status,
                failures,
            )

    def finish_short_rest(
        self,
        character_id: int,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            status = CharacterCombatStatus(state["status"])
            if status is CharacterCombatStatus.RECOVERING:
                status = CharacterCombatStatus.ACTIVE
                connection.execute(
                    """
                    UPDATE character_combat_states
                    SET status = 'active'
                    WHERE character_id = ?
                    """,
                    (character_id,),
                )
            return CharacterCombatState(
                character_id,
                status,
                int(state["failed_death_saves"]),
            )

    def set_hp(self, discord_user_id: int, hp: int) -> Character:
        character = self._require_character(discord_user_id)
        if not -character.max_hp <= hp <= character.max_hp:
            raise InvalidHitPointsError(
                f"HP must be between {-character.max_hp} and "
                f"{character.max_hp} for {character.name}."
            )
        assert character.character_id is not None
        with self._connect() as connection:
            self._ensure_character_combat_state_row(
                connection,
                character.character_id,
            )
            if hp <= -character.max_hp:
                status = CharacterCombatStatus.DEAD
            elif hp <= 0:
                status = CharacterCombatStatus.DOWNED
            else:
                status = CharacterCombatStatus.ACTIVE
            connection.execute(
                """
                UPDATE characters SET hp = ?
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (hp, discord_user_id),
            )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = 0
                WHERE character_id = ?
                """,
                (status.value, character.character_id),
            )
        return self._require_character(discord_user_id)

    def adjust_character_hunger(
        self,
        character_id: int,
        amount: int,
    ) -> Character:
        """Adjust Hunger by a signed amount, clamped to the 0-100 range."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT hunger FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError(
                    f"Character {character_id} does not exist."
                )
            hunger = max(0, min(100, int(row["hunger"]) + amount))
            connection.execute(
                "UPDATE characters SET hunger = ? WHERE id = ?",
                (hunger, character_id),
            )
            character_row = connection.execute(
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
            assert character_row is not None
            return self._to_character_with_skills(connection, character_row)

    def set_stance(self, discord_user_id: int, stance: Stance) -> Character:
        self._require_character(discord_user_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE characters SET stance = ?
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (stance.value, discord_user_id),
            )
        return self._require_character(discord_user_id)
