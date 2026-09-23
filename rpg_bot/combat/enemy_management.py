"""Enemy participation management for active combat scenes."""

from __future__ import annotations

from dataclasses import replace

from .errors import CombatError
from .models import CombatScene, CombatantKind, CombatantState, LandmarkRelation


class CombatEnemyManagementMixin:
    """Add and remove enemy combatants from the active scene."""

    def add_enemies(
        self,
        guild_id: int,
        template_id: str,
        *,
        landmark_id: str | None = None,
        quantity: int = 1,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= 20
        ):
            raise CombatError("Enemy quantity must be an integer from 1 to 20.")

        template = self.world.get_enemy_template(template_id)
        if template is None:
            raise CombatError(
                f"Enemy template '{template_id}' does not exist."
            )

        destination_id = landmark_id or self.CENTER_LANDMARK_ID
        if scene.landmark(destination_id) is None:
            raise CombatError(
                f"Unknown combat landmark '{destination_id}'."
            )

        for _ in range(quantity):
            enemy = self.world.place_enemy(
                scene.room_id,
                template.template_id,
            )
            initiative_roll, initiative_score = self._roll_initiative(
                template.insight
            )
            current_combatant = scene.current_combatant()
            movement_budget = self._enemy_movement_budget(enemy.id)
            candidate = CombatantState(
                CombatantKind.ENEMY,
                enemy.id,
                enemy.name,
                destination_id,
                LandmarkRelation.AT,
                initiative_roll,
                initiative_score,
                movement_budget=movement_budget,
                movement_remaining=movement_budget,
            )
            has_passed_current_turn = (
                current_combatant is not None
                and candidate.initiative_key < current_combatant.initiative_key
            )
            candidate = replace(
                candidate,
                acted_this_round=has_passed_current_turn,
            )
            try:
                self.repository.add_combatant(
                    scene.id,
                    candidate,
                )
                destination = scene.landmark(destination_id)
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_joined",
                    (
                        f"{enemy.name} joined combat at "
                        f"{destination.name if destination is not None else destination_id}."
                    ),
                    actor_kind=CombatantKind.ENEMY,
                    actor_source_id=enemy.id,
                    actor_name=enemy.name,
                )
            except ValueError as error:
                self.world.remove_entity(enemy.id)
                raise CombatError(str(error)) from error

        return self._ensure_turn(guild_id)

    def remove_enemy(
        self,
        guild_id: int,
        enemy_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        removed = next(
            (
                combatant
                for combatant in scene.combatants
                if combatant.kind is CombatantKind.ENEMY
                and combatant.source_id == enemy_id
            ),
            None,
        )
        if removed is None:
            raise CombatError(
                f"Enemy '{enemy_id}' is not in the active combat scene."
            )

        removing_current = (
            scene.current_turn_kind is CombatantKind.ENEMY
            and scene.current_turn_source_id == enemy_id
        )
        try:
            self.repository.remove_combatant(
                scene.id,
                CombatantKind.ENEMY,
                enemy_id,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "combatant_removed",
                f"{removed.name} was removed from combat.",
                actor_kind=removed.kind,
                actor_source_id=removed.source_id,
                actor_name=removed.name,
            )
            if removing_current:
                remaining_scene = self._require_current(guild_id)
                if not remaining_scene.combatants:
                    self.repository.set_turn(
                        scene.id,
                        scene.round_number,
                        None,
                        None,
                    )
                    return self._require_current(guild_id)

                available = self._available_turn_combatants(
                    remaining_scene
                )
                next_round = scene.round_number
                if not available:
                    self.repository.set_all_combatants_acted(scene.id, False)
                    next_round += 1
                    remaining_scene = self._require_current(guild_id)
                    available = self._available_turn_combatants(
                        remaining_scene
                    )
                if not available:
                    self.repository.set_turn(
                        scene.id,
                        next_round,
                        None,
                        None,
                    )
                    return self._require_current(guild_id)

                next_combatant = available[0]
                self.repository.reset_combatant_movement(
                    scene.id,
                    next_combatant.kind,
                    next_combatant.source_id,
                )
                self.repository.reset_standard_action(
                    scene.id,
                    next_combatant.kind,
                    next_combatant.source_id,
                )
                self.repository.set_turn(
                    scene.id,
                    next_round,
                    next_combatant.kind,
                    next_combatant.source_id,
                )
                self.repository.append_log(
                    scene.id,
                    next_round,
                    "turn_started",
                    f"{next_combatant.name}'s turn began.",
                    actor_kind=next_combatant.kind,
                    actor_source_id=next_combatant.source_id,
                    actor_name=next_combatant.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        ensured = self._ensure_turn(guild_id)
        if ensured.current_combatant() is None:
            return ensured
        return self._resolve_current_death_save(guild_id)
