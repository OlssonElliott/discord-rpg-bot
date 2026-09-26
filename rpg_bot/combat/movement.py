"""Combatant movement orchestration."""

from __future__ import annotations

from .errors import CombatError
from .models import CombatScene, CombatantKind, CoverLevel, LandmarkRelation
from .navigation import movement_legs, route_between
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

    def move_combatant_toward_combatant(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
        target_kind: CombatantKind | str,
        target_source_id: str,
    ) -> CombatScene:
        """Spend movement toward another combatant's exact tactical position."""
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            parsed_target_kind = (
                target_kind
                if isinstance(target_kind, CombatantKind)
                else CombatantKind(target_kind)
            )
            combatant = next(
                item
                for item in scene.combatants
                if item.kind is parsed_kind
                and item.source_id == source_id
            )
            target = next(
                item
                for item in scene.combatants
                if item.kind is parsed_target_kind
                and item.source_id == target_source_id
            )
            if combatant is target:
                raise CombatError("A combatant cannot move toward themselves.")

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

            if not target.is_between_landmarks:
                return self.move_combatant_toward(
                    guild_id,
                    parsed_kind,
                    source_id,
                    target.landmark_id,
                    LandmarkRelation.AT,
                )

            if combatant.movement_remaining <= 0:
                raise CombatError(
                    f"{combatant.name} has no movement remaining this turn."
                )

            target_source = target.route_source_landmark_id
            target_destination = target.route_destination_landmark_id
            assert target_source is not None
            assert target_destination is not None

            target_route = route_between(
                scene,
                target_source,
                target_destination,
            )
            if target_route is None:
                raise CombatError(
                    "The route under the target no longer exists."
                )

            same_route = (
                combatant.is_between_landmarks
                and {
                    combatant.route_source_landmark_id,
                    combatant.route_destination_landmark_id,
                }
                == {target_source, target_destination}
                and combatant.route_cost == target.route_cost
            )
            if same_route:
                assert combatant.route_source_landmark_id is not None
                assert combatant.route_destination_landmark_id is not None
                target_progress = (
                    target.route_progress
                    if target.route_source_landmark_id
                    == combatant.route_source_landmark_id
                    else target.route_cost - target.route_progress
                )
                delta = target_progress - combatant.route_progress
                distance = abs(delta)
                if distance == 0:
                    return scene

                spent = min(
                    combatant.movement_remaining,
                    distance,
                )
                new_progress = (
                    combatant.route_progress
                    + (spent if delta > 0 else -spent)
                )
                movement_remaining = (
                    combatant.movement_remaining - spent
                )
                self.repository.set_combatant_position(
                    scene.id,
                    parsed_kind,
                    source_id,
                    combatant.route_source_landmark_id,
                    LandmarkRelation.AT,
                    movement_remaining=movement_remaining,
                    route_source_landmark_id=(
                        combatant.route_source_landmark_id
                    ),
                    route_destination_landmark_id=(
                        combatant.route_destination_landmark_id
                    ),
                    route_progress=new_progress,
                    route_cost=combatant.route_cost,
                )
                reached = new_progress == target_progress
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_moved",
                    (
                        f"{combatant.name} moved "
                        f"{'to' if reached else 'toward'} "
                        f"{target.name} on the route "
                        f"({new_progress}/{combatant.route_cost})."
                    ),
                    actor_kind=combatant.kind,
                    actor_source_id=combatant.source_id,
                    actor_name=combatant.name,
                )
                return self._require_current(guild_id)

            if target_route.blocked:
                raise CombatError(
                    f"The route to {target.name} is blocked."
                )

            candidates: list[
                tuple[
                    int,
                    str,
                    str,
                    int,
                    list[tuple[str, str, object, int]],
                ]
            ] = []
            for endpoint, other_endpoint, partial_cost in (
                (
                    target_source,
                    target_destination,
                    target.route_progress,
                ),
                (
                    target_destination,
                    target_source,
                    target.route_cost - target.route_progress,
                ),
            ):
                try:
                    legs = movement_legs(
                        scene,
                        combatant,
                        endpoint,
                    )
                except ValueError:
                    continue
                endpoint_cost = sum(
                    route.movement_cost - already_moved
                    for _, _, route, already_moved in legs
                )
                candidates.append(
                    (
                        endpoint_cost + partial_cost,
                        endpoint,
                        other_endpoint,
                        partial_cost,
                        legs,
                    )
                )

            if not candidates:
                raise CombatError(
                    f"No unblocked route reaches {target.name}."
                )

            (
                _,
                endpoint,
                other_endpoint,
                target_progress_from_endpoint,
                legs,
            ) = min(candidates, key=lambda candidate: candidate[0])

            movement_remaining = combatant.movement_remaining
            arrived_landmark_id = combatant.landmark_id

            for (
                leg_source_id,
                leg_destination_id,
                route,
                already_moved,
            ) in legs:
                leg_remaining = route.movement_cost - already_moved
                if movement_remaining < leg_remaining:
                    travelled = already_moved + movement_remaining
                    self.repository.set_combatant_position(
                        scene.id,
                        parsed_kind,
                        source_id,
                        leg_source_id,
                        LandmarkRelation.AT,
                        movement_remaining=0,
                        route_source_landmark_id=leg_source_id,
                        route_destination_landmark_id=leg_destination_id,
                        route_progress=travelled,
                        route_cost=route.movement_cost,
                    )
                    self.repository.append_log(
                        scene.id,
                        scene.round_number,
                        "combatant_moved",
                        (
                            f"{combatant.name} moved toward {target.name} "
                            f"and stopped on the route "
                            f"({travelled}/{route.movement_cost})."
                        ),
                        actor_kind=combatant.kind,
                        actor_source_id=combatant.source_id,
                        actor_name=combatant.name,
                    )
                    return self._require_current(guild_id)

                movement_remaining -= leg_remaining
                arrived_landmark_id = leg_destination_id

            if movement_remaining == 0:
                self.repository.set_combatant_position(
                    scene.id,
                    parsed_kind,
                    source_id,
                    arrived_landmark_id,
                    LandmarkRelation.AT,
                    movement_remaining=0,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_moved",
                    (
                        f"{combatant.name} moved toward {target.name} "
                        f"and reached {arrived_landmark_id}."
                    ),
                    actor_kind=combatant.kind,
                    actor_source_id=combatant.source_id,
                    actor_name=combatant.name,
                )
                return self._require_current(guild_id)

            final_spent = min(
                movement_remaining,
                target_progress_from_endpoint,
            )
            movement_remaining -= final_spent
            if final_spent == target_progress_from_endpoint:
                final_progress = target_progress_from_endpoint
                reached = True
            else:
                final_progress = final_spent
                reached = False

            self.repository.set_combatant_position(
                scene.id,
                parsed_kind,
                source_id,
                endpoint,
                LandmarkRelation.AT,
                movement_remaining=movement_remaining,
                route_source_landmark_id=endpoint,
                route_destination_landmark_id=other_endpoint,
                route_progress=final_progress,
                route_cost=target.route_cost,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "combatant_moved",
                (
                    f"{combatant.name} moved "
                    f"{'to' if reached else 'toward'} {target.name} "
                    f"on the route "
                    f"({final_progress}/{target.route_cost})."
                ),
                actor_kind=combatant.kind,
                actor_source_id=combatant.source_id,
                actor_name=combatant.name,
            )
        except CombatError:
            raise
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
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
