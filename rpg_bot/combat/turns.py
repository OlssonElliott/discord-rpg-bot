"""Turn-order orchestration for active combat scenes."""

from __future__ import annotations

from .errors import CombatError
from .models import CombatScene, CombatantKind, CombatantState
from ..characters.models import CharacterCombatStatus


class CombatTurnMixin:
    """Manage combat turn eligibility, order, and initiative."""

    def _combatant_can_take_turn(
        self,
        combatant: CombatantState,
    ) -> bool:
        if combatant.kind is CombatantKind.ENEMY:
            return True
        try:
            character_id = int(combatant.source_id)
        except ValueError:
            return False
        state = self.database.get_character_combat_state(character_id)
        return state.status not in {
            CharacterCombatStatus.STABLE,
            CharacterCombatStatus.DEAD,
        }

    def _available_turn_combatants(
        self,
        scene: CombatScene,
    ) -> list[CombatantState]:
        return [
            combatant
            for combatant in scene.initiative_order()
            if not combatant.acted_this_round
            and self._combatant_can_take_turn(combatant)
        ]

    @staticmethod
    def _turn_index(scene: CombatScene) -> int | None:
        ordered = scene.initiative_order()
        for index, combatant in enumerate(ordered):
            if (
                combatant.kind is scene.current_turn_kind
                and combatant.source_id == scene.current_turn_source_id
            ):
                return index
        return None

    def _ensure_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if scene.current_combatant() is not None or not scene.combatants:
            return scene
        available = self._available_turn_combatants(scene)
        if not available:
            self.repository.set_all_combatants_acted(scene.id, False)
            scene = self._require_current(guild_id)
            available = self._available_turn_combatants(scene)
        if not available:
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                None,
                None,
            )
            return self._require_current(guild_id)
        first = available[0]
        try:
            self.repository.reset_combatant_movement(
                scene.id,
                first.kind,
                first.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                first.kind,
                first.source_id,
            )
            self.repository.reset_dashed(
                scene.id,
                first.kind,
                first.source_id,
            )

            self.repository.reset_defending(
                scene.id,
                first.kind,
                first.source_id,
            )
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                first.kind,
                first.source_id,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "turn_started",
                f"{first.name}'s turn began.",
                actor_kind=first.kind,
                actor_source_id=first.source_id,
                actor_name=first.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._resolve_current_death_save(guild_id)

    def next_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if not scene.combatants:
            return scene
        current = scene.current_combatant()
        if current is None:
            return self._ensure_turn(guild_id)

        try:
            self.repository.set_combatant_acted(
                scene.id,
                current.kind,
                current.source_id,
                True,
            )
            updated = self._require_current(guild_id)
            available = self._available_turn_combatants(updated)
            next_round = scene.round_number
            if not available:
                self.repository.set_all_combatants_acted(scene.id, False)
                next_round += 1
                updated = self._require_current(guild_id)
                available = self._available_turn_combatants(updated)
            if not available:
                self.repository.set_turn(
                    scene.id,
                    next_round,
                    None,
                    None,
                )
                return self._require_current(guild_id)

            target = available[0]
            self.repository.reset_combatant_movement(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_dashed(
                scene.id,
                target.kind,
                target.source_id,
            )

            self.repository.reset_defending(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.set_turn(
                scene.id,
                next_round,
                target.kind,
                target.source_id,
            )
            self.repository.append_log(
                scene.id,
                next_round,
                "turn_started",
                f"{target.name}'s turn began.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._resolve_current_death_save(guild_id)

    def previous_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if not scene.combatants:
            return scene
        if scene.current_combatant() is None:
            return self._ensure_turn(guild_id)

        ordered = scene.initiative_order()
        current_index = self._turn_index(scene)
        assert current_index is not None
        target = next(
            (
                ordered[(current_index - offset) % len(ordered)]
                for offset in range(1, len(ordered) + 1)
                if self._combatant_can_take_turn(
                    ordered[(current_index - offset) % len(ordered)]
                )
            ),
            None,
        )
        if target is None:
            return scene
        previous_round = scene.round_number
        try:
            if current_index == 0 and scene.round_number > 1:
                previous_round -= 1
                self.repository.set_all_combatants_acted(scene.id, True)
            self.repository.set_combatant_acted(
                scene.id,
                target.kind,
                target.source_id,
                False,
            )
            self.repository.reset_combatant_movement(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_dashed(
                scene.id,
                target.kind,
                target.source_id,
            )

            self.repository.reset_defending(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.set_turn(
                scene.id,
                previous_round,
                target.kind,
                target.source_id,
            )
            self.repository.append_log(
                scene.id,
                previous_round,
                "turn_rewound",
                f"DM moved the turn back to {target.name}.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def jump_turn(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            target = next(
                combatant
                for combatant in scene.combatants
                if combatant.kind is parsed_kind
                and combatant.source_id == source_id
            )
            if not self._combatant_can_take_turn(target):
                raise CombatError(
                    f"{target.name} cannot take a turn in their current state."
                )
            self.repository.reset_combatant_movement(
                scene.id,
                parsed_kind,
                source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                parsed_kind,
                source_id,
            )
            self.repository.reset_dashed(
                scene.id,
                parsed_kind,
                source_id,
            )

            self.repository.reset_defending(
                scene.id,
                parsed_kind,
                source_id,
            )
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                parsed_kind,
                source_id,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "turn_changed",
                f"DM set the current turn to {target.name}.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def set_initiative(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
        initiative_score: int,
    ) -> CombatScene:
        if (
            isinstance(initiative_score, bool)
            or not isinstance(initiative_score, int)
        ):
            raise CombatError("Initiative must be a whole number.")
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            target = next(
                combatant
                for combatant in scene.combatants
                if combatant.kind is parsed_kind
                and combatant.source_id == source_id
            )
            self.repository.set_initiative(
                scene.id,
                parsed_kind,
                source_id,
                initiative_score,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "initiative_changed",
                (
                    f"{target.name}'s initiative changed from "
                    f"{target.initiative_score} to {initiative_score}."
                ),
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)
