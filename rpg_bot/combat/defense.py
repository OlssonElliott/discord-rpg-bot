"""Defend action orchestration."""

from __future__ import annotations

from .errors import CombatError
from .models import CombatScene, CombatantKind
from ..characters.models import CharacterCombatStatus


class CombatDefenseMixin:
    """Standard Action that prepares the next defense roll."""

    def defend(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        defender = scene.current_combatant()
        if defender is None:
            raise CombatError("There is no current combatant.")
        if defender.kind is not CombatantKind.CHARACTER:
            raise CombatError("Only a character can use Defend.")
        if defender.standard_action_spent:
            raise CombatError(
                f"{defender.name} has already spent their Standard Action."
            )

        character = self._character_by_source_id(defender.source_id)
        assert character.character_id is not None
        state = self.database.get_character_combat_state(character.character_id)
        if state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{defender.name} cannot Defend while {state.status.value}."
            )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                defender.kind,
                defender.source_id,
                True,
            )
            self.repository.set_defending(
                scene.id,
                defender.kind,
                defender.source_id,
                True,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "defend_prepared",
                (
                    f"{defender.name} used Defend. "
                    "Their next defense roll before their next turn has Advantage."
                ),
                actor_kind=defender.kind,
                actor_source_id=defender.source_id,
                actor_name=defender.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id)
