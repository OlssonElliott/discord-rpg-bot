"""Combat death-save orchestration."""

from __future__ import annotations

import math

from .errors import CombatError
from .models import CombatScene, CombatantKind, DeathSaveResult
from ..characters.models import CharacterCombatStatus


class CombatDeathSaveMixin:
    """Resolve death saves for downed characters."""

    def _resolve_current_death_save(
        self,
        guild_id: int,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        current = scene.current_combatant()
        if current is None or current.kind is not CombatantKind.CHARACTER:
            return scene

        character = self._character_by_source_id(current.source_id)
        assert character.character_id is not None
        state = self.database.get_character_combat_state(
            character.character_id
        )
        if state.status is not CharacterCombatStatus.DOWNED:
            return scene

        resolved, _ = self.roll_death_save(
            guild_id,
            current.source_id,
        )
        return resolved

    def roll_death_save(
        self,
        guild_id: int,
        character_source_id: str,
    ) -> tuple[CombatScene, DeathSaveResult]:
        scene = self._require_current(guild_id)
        current = scene.current_combatant()
        if (
            current is None
            or current.kind is not CombatantKind.CHARACTER
            or current.source_id != character_source_id
        ):
            raise CombatError(
                "Death saves can only be rolled for the current character."
            )

        character = self._character_by_source_id(character_source_id)
        assert character.character_id is not None
        state = self.database.get_character_combat_state(
            character.character_id
        )
        if state.status is not CharacterCombatStatus.DOWNED:
            raise CombatError(f"{character.name} is not downed.")
        if current.standard_action_spent:
            raise CombatError(
                f"{character.name}'s death save is already resolved this turn."
            )

        dc = 10 + math.ceil(abs(character.hp) / 2)
        vitality = self.database.get_character_attribute(
            character.character_id,
            "vitality",
        )
        modifier = (vitality - 10) // 2
        roll = self._roll_die(20)
        total = roll + modifier
        success = roll == 20 or (
            roll != 1
            and total >= dc
        )
        updated_state = self.database.record_death_save(
            character.character_id,
            success=success,
        )

        result = DeathSaveResult(
            character_source_id=current.source_id,
            character_name=character.name,
            hp=character.hp,
            dc=dc,
            roll=roll,
            modifier=modifier,
            total=total,
            success=success,
            failed_death_saves=updated_state.failed_death_saves,
            status=updated_state.status.value,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                current.kind,
                current.source_id,
                True,
            )
            self.repository.set_movement_remaining(
                scene.id,
                current.kind,
                current.source_id,
                0,
            )
            if success:
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "death_save_success",
                    (
                        f"{character.name} rolled a death save: "
                        f"{roll}{modifier:+d} = {total} vs DC {dc}, success. "
                        f"{character.name} is stable."
                    ),
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_stabilized",
                    f"{character.name} stabilized at {character.hp} HP.",
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
            else:
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "death_save_failed",
                    (
                        f"{character.name} rolled a death save: "
                        f"{roll}{modifier:+d} = {total} vs DC {dc}, failed. "
                        f"Failed death saves: "
                        f"{updated_state.failed_death_saves}/3."
                    ),
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )

            if updated_state.status is CharacterCombatStatus.DEAD:
                self.repository.remove_combatant(
                    scene.id,
                    current.kind,
                    current.source_id,
                )
                self.repository.set_turn(
                    scene.id,
                    scene.round_number,
                    None,
                    None,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_died",
                    f"{character.name} died after three failed death saves.",
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        if updated_state.status is CharacterCombatStatus.DEAD:
            return self._ensure_turn(guild_id), result
        return self._require_current(guild_id), result
