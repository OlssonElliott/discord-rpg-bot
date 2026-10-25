"""Combat landmark mutation operations."""

from __future__ import annotations

import math
from uuid import uuid4

from .errors import CombatError
from .layout import next_open_position
from .models import (
    CombatLandmark,
    CombatRouteEffect,
    CombatScene,
    CoverLevel,
    LandmarkDistance,
    RouteTerrain,
)


class CombatLandmarkMixin:
    """Manage landmarks and routes for an active combat scene."""

    def add_landmark(
        self,
        guild_id: int,
        name: str,
        description: str | None = None,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        name = name.strip()
        if not name:
            raise CombatError("Landmark name is required.")
        x, y = next_open_position(scene.landmarks)
        landmark = CombatLandmark(
            id=f"custom:{uuid4().hex}",
            name=name,
            description=description.strip() if description and description.strip() else None,
            feature_type="custom",
            x=x,
            y=y,
        )
        try:
            self.repository.add_landmark(scene.id, landmark)
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self.auto_connect_landmark(guild_id, landmark.id)

    def disconnect_landmarks(
        self,
        guild_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        route_ids = {source_landmark_id, destination_landmark_id}
        if any(
            combatant.is_between_landmarks
            and {
                combatant.route_source_landmark_id,
                combatant.route_destination_landmark_id,
            } == route_ids
            for combatant in scene.combatants
        ):
            raise CombatError(
                "Move combatants off this connection before removing it."
            )
        try:
            self.repository.delete_route(
                scene.id,
                source_landmark_id,
                destination_landmark_id,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def remove_landmark(
        self,
        guild_id: int,
        landmark_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        landmark = scene.landmark(landmark_id)
        if landmark is None:
            raise CombatError(f"Unknown combat landmark '{landmark_id}'.")
        if any(
            combatant.landmark_id == landmark_id
            or combatant.route_source_landmark_id == landmark_id
            or combatant.route_destination_landmark_id == landmark_id
            for combatant in scene.combatants
        ):
            raise CombatError(
                "Move combatants away from this landmark before removing it."
            )
        try:
            self.repository.delete_landmark(scene.id, landmark_id)
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def set_landmark_position(
        self,
        guild_id: int,
        landmark_id: str,
        x: float,
        y: float,
    ) -> CombatScene:
        if (
            isinstance(x, bool)
            or isinstance(y, bool)
            or not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
        ):
            raise CombatError("Landmark coordinates must be numbers.")
        x = float(x)
        y = float(y)
        if (
            not math.isfinite(x)
            or not math.isfinite(y)
            or not (-1 <= x <= 2)
            or not (-1 <= y <= 2)
        ):
            raise CombatError(
                "Landmark coordinates must stay within the combat canvas."
            )
        scene = self._require_current(guild_id)
        try:
            self.repository.set_landmark_position(scene.id, landmark_id, x, y)
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def set_landmark_cover(
        self,
        guild_id: int,
        landmark_id: str,
        cover: CoverLevel | str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        landmark = scene.landmark(landmark_id)
        if landmark is None:
            raise CombatError(f"Unknown combat landmark '{landmark_id}'.")
        try:
            parsed_cover = (
                cover if isinstance(cover, CoverLevel) else CoverLevel(cover)
            )
        except ValueError as error:
            raise CombatError(f"Unknown cover level '{cover}'.") from error
        if landmark.synthetic and parsed_cover is not CoverLevel.NONE:
            raise CombatError("Synthetic room anchors cannot provide cover.")
        try:
            self.repository.set_landmark_cover(
                scene.id,
                landmark_id,
                parsed_cover,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def disconnect_landmark_routes(
        self,
        guild_id: int,
        landmark_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        if scene.landmark(landmark_id) is None:
            raise CombatError(f"Unknown combat landmark '{landmark_id}'.")
        if any(
            combatant.is_between_landmarks
            and landmark_id in {
                combatant.route_source_landmark_id,
                combatant.route_destination_landmark_id,
            }
            for combatant in scene.combatants
        ):
            raise CombatError(
                "Move combatants off this landmark's connections before removing them."
            )
        self.repository.delete_routes_for_landmark(scene.id, landmark_id)
        return self._require_current(guild_id)

    def disconnect_all_routes(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if any(combatant.is_between_landmarks for combatant in scene.combatants):
            raise CombatError(
                "Move combatants off all connections before removing them."
            )
        self.repository.delete_all_routes(scene.id)
        return self._require_current(guild_id)

    def connect_landmarks(
        self,
        guild_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
        distance: LandmarkDistance | str,
        *,
        terrain: RouteTerrain | str = RouteTerrain.NORMAL,
        base_blocked: bool = False,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        route_ids = {source_landmark_id, destination_landmark_id}
        if any(
            combatant.is_between_landmarks
            and {
                combatant.route_source_landmark_id,
                combatant.route_destination_landmark_id,
            } == route_ids
            for combatant in scene.combatants
        ):
            raise CombatError(
                "Finish movement on this connection before changing it."
            )
        try:
            parsed_distance = (
                distance
                if isinstance(distance, LandmarkDistance)
                else LandmarkDistance(distance)
            )
            parsed_terrain = (
                terrain
                if isinstance(terrain, RouteTerrain)
                else RouteTerrain(terrain)
            )
            self.repository.set_route(
                scene.id,
                source_landmark_id,
                destination_landmark_id,
                parsed_distance,
                terrain=parsed_terrain,
                base_blocked=base_blocked,
                automatic=False,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def add_route_effect(
        self,
        guild_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
        name: str,
        effect_type: str,
        *,
        blocks_movement: bool = False,
        movement_cost_modifier: int = 0,
        remaining_rounds: int | None = None,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        name = name.strip()
        effect_type = effect_type.strip()
        if not name:
            raise CombatError("Route effect name is required.")
        if not effect_type:
            raise CombatError("Route effect type is required.")
        if remaining_rounds is not None and remaining_rounds <= 0:
            raise CombatError("Effect duration must be greater than zero.")

        effect = CombatRouteEffect(
            id=f"route-effect:{uuid4().hex}",
            name=name,
            effect_type=effect_type,
            blocks_movement=blocks_movement,
            movement_cost_modifier=movement_cost_modifier,
            remaining_rounds=remaining_rounds,
        )
        try:
            self.repository.add_route_effect(
                scene.id,
                source_landmark_id,
                destination_landmark_id,
                effect,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def remove_route_effect(
        self,
        guild_id: int,
        effect_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        try:
            self.repository.delete_route_effect(
                scene.id,
                effect_id,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)
