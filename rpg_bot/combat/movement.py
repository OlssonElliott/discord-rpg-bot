"""Combatant movement orchestration."""

from __future__ import annotations

from .errors import CombatError
from .models import CombatScene, CombatantKind, CoverLevel, LandmarkRelation
from .navigation import movement_legs
from ..characters.models import CharacterCombatStatus


class CombatMovementMixin:
    """Move combatants directly or by spending turn movement."""

    def dash(self, guild_id: int) -> CombatScene:
        """Spend the Standard Action to gain another full movement budget."""
        scene = self._require_current(guild_id)
        actor = scene.current_combatant()
        if actor is None:
            raise CombatError("There is no current combatant.")
        if actor.standard_action_spent:
            raise CombatError(
                f"{actor.name} has already spent their Standard Action."
            )

        if actor.kind is CombatantKind.CHARACTER:
            character = self._character_by_source_id(actor.source_id)
            assert character.character_id is not None
            state = self.database.get_character_combat_state(
                character.character_id
            )
            if state.status not in {
                CharacterCombatStatus.ACTIVE,
                CharacterCombatStatus.RECOVERING,
            }:
                raise CombatError(
                    f"{actor.name} cannot Dash while {state.status.value}."
                )
            if (
                self._character_load_state(character.character_id)
                == "over_encumbered"
            ):
                raise CombatError(
                    f"{actor.name} is over-encumbered and cannot Dash."
                )

        self.repository.set_movement_remaining(
            scene.id,
            actor.kind,
            actor.source_id,
            actor.movement_remaining + actor.movement_budget,
        )
        self.repository.set_dashed(
            scene.id,
            actor.kind,
            actor.source_id,
            True,
        )
        self.repository.set_standard_action_spent(
            scene.id,
            actor.kind,
            actor.source_id,
            True,
        )
        self.repository.append_log(
            scene.id,
            scene.round_number,
            "combatant_dashed",
            (
                f"{actor.name} Dashed for +{actor.movement_budget} movement "
                f"this turn."
            ),
            actor_kind=actor.kind,
            actor_source_id=actor.source_id,
            actor_name=actor.name,
        )
        return self._require_current(guild_id)

    def move_combatant(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
        landmark_id: str,
        relation: LandmarkRelation | str = LandmarkRelation.AT,
    ) -> CombatScene:
        """DM repositioning that does not spend turn movement."""
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            parsed_relation = (
                relation
                if isinstance(relation, LandmarkRelation)
                else LandmarkRelation(relation)
            )
            combatant = next(
                item
                for item in scene.combatants
                if item.kind is parsed_kind and item.source_id == source_id
            )
            landmark = scene.landmark(landmark_id)
            if landmark is None:
                raise CombatError(
                    f"Unknown combat landmark '{landmark_id}'."
                )
            if (
                parsed_relation is LandmarkRelation.BEHIND
                and landmark.cover is CoverLevel.NONE
            ):
                raise CombatError(
                    f"{landmark.name} does not support a behind position."
                )
            self.repository.set_combatant_position(
                scene.id,
                parsed_kind,
                source_id,
                landmark_id,
                parsed_relation,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "combatant_moved",
                (
                    f"{combatant.name} moved {parsed_relation.value} "
                    f"{landmark.name if landmark is not None else landmark_id}."
                ),
                actor_kind=combatant.kind,
                actor_source_id=combatant.source_id,
                actor_name=combatant.name,
            )
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def move_combatant_toward(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
        landmark_id: str,
        relation: LandmarkRelation | str = LandmarkRelation.AT,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        try:
            parsed_kind = kind if isinstance(kind, CombatantKind) else CombatantKind(kind)
            parsed_relation = (
                relation
                if isinstance(relation, LandmarkRelation)
                else LandmarkRelation(relation)
            )
            combatant = next(
                item
                for item in scene.combatants
                if item.kind is parsed_kind and item.source_id == source_id
            )

            if parsed_kind is CombatantKind.CHARACTER:
                character = self._character_by_source_id(source_id)
                assert character.character_id is not None
                state = self.database.get_character_combat_state(
                    character.character_id
                )
                if state.status not in {
                    CharacterCombatStatus.ACTIVE,
                    CharacterCombatStatus.RECOVERING,
                }:
                    raise CombatError(
                        f"{combatant.name} cannot move while "
                        f"{state.status.value}."
                    )

            if (
                scene.current_turn_kind is not parsed_kind
                or scene.current_turn_source_id != source_id
            ):
                raise CombatError(
                    "Only the current combatant can spend movement."
                )

            destination = scene.landmark(landmark_id)
            if destination is None:
                raise CombatError(
                    f"Unknown combat landmark '{landmark_id}'."
                )
            if (
                parsed_relation is LandmarkRelation.BEHIND
                and destination.cover is CoverLevel.NONE
            ):
                raise CombatError(
                    f"{destination.name} does not support a behind position."
                )

            if (
                not combatant.is_between_landmarks
                and combatant.landmark_id == landmark_id
            ):
                self.repository.set_combatant_position(
                    scene.id,
                    parsed_kind,
                    source_id,
                    landmark_id,
                    parsed_relation,
                    movement_remaining=combatant.movement_remaining,
                )
                return self._require_current(guild_id)

            if combatant.movement_remaining <= 0:
                raise CombatError(
                    f"{combatant.name} has no movement remaining this turn."
                )

            legs = movement_legs(
                scene,
                combatant,
                landmark_id,
            )
            movement_remaining = combatant.movement_remaining
            arrived_landmark_id = combatant.landmark_id
            completed = False

            for (
                leg_source_id,
                leg_destination_id,
                route,
                already_moved,
            ) in legs:
                leg_remaining = route.movement_cost - already_moved

                if movement_remaining < leg_remaining:
                    travelled_from_leg_source = (
                        already_moved + movement_remaining
                    )

                    self.repository.set_combatant_position(
                        scene.id,
                        parsed_kind,
                        source_id,
                        leg_source_id,
                        LandmarkRelation.AT,
                        movement_remaining=0,
                        route_source_landmark_id=leg_source_id,
                        route_destination_landmark_id=leg_destination_id,
                        route_progress=travelled_from_leg_source,
                        route_cost=route.movement_cost,
                    )

                    source = scene.landmark(leg_source_id)
                    route_destination = scene.landmark(
                        leg_destination_id
                    )
                    self.repository.append_log(
                        scene.id,
                        scene.round_number,
                        "combatant_moved",
                        (
                            f"{combatant.name} moved between "
                            f"{source.name if source is not None else leg_source_id} "
                            f"and "
                            f"{route_destination.name if route_destination is not None else leg_destination_id} "
                            f"({travelled_from_leg_source}/"
                            f"{route.movement_cost})."
                        ),
                        actor_kind=combatant.kind,
                        actor_source_id=combatant.source_id,
                        actor_name=combatant.name,
                    )
                    return self._require_current(guild_id)

                movement_remaining -= leg_remaining
                arrived_landmark_id = leg_destination_id

                if arrived_landmark_id == landmark_id:
                    completed = True
                    break
                if movement_remaining == 0:
                    break

            final_relation = (
                parsed_relation
                if completed
                else LandmarkRelation.AT
            )
            self.repository.set_combatant_position(
                scene.id,
                parsed_kind,
                source_id,
                arrived_landmark_id,
                final_relation,
                movement_remaining=movement_remaining,
            )

            arrived = scene.landmark(arrived_landmark_id)
            if completed:
                message = (
                    f"{combatant.name} moved {parsed_relation.value} "
                    f"{destination.name}. "
                    f"{movement_remaining}/{combatant.movement_budget} "
                    f"movement remains."
                )
            else:
                message = (
                    f"{combatant.name} reached "
                    f"{arrived.name if arrived is not None else arrived_landmark_id} "
                    f"with no movement remaining."
                )

            self.repository.append_log(
                scene.id,
                scene.round_number,
                "combatant_moved",
                message,
                actor_kind=combatant.kind,
                actor_source_id=combatant.source_id,
                actor_name=combatant.name,
            )
        except CombatError:
            raise
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)
