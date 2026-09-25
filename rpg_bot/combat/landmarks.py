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
            self.repository.set_route(
                scene.id,
                self.CENTER_LANDMARK_ID,
                landmark.id,
                LandmarkDistance.CLOSE,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

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
        if landmark.feature_type != "custom":
            raise CombatError("Only manually added combat landmarks can be removed.")
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
            or not (0 <= x <= 1)
            or not (0 <= y <= 1)
        ):
            raise CombatError(
                "Landmark coordinates must be normalized between 0 and 1."
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

    @staticmethod
    def _distance_between(
        source: CombatLandmark,
        target: CombatLandmark,
    ) -> float:
        assert source.x is not None and source.y is not None
        assert target.x is not None and target.y is not None
        return math.hypot(target.x - source.x, target.y - source.y)

    @classmethod
    def _landmark_between(
        cls,
        source: CombatLandmark,
        target: CombatLandmark,
        candidate: CombatLandmark,
    ) -> bool:
        if (
            candidate.id in {source.id, target.id}
            or candidate.x is None
            or candidate.y is None
        ):
            return False
        direct = cls._distance_between(source, target)
        if direct <= 0:
            return False
        source_leg = cls._distance_between(source, candidate)
        target_leg = cls._distance_between(candidate, target)
        if source_leg >= direct or target_leg >= direct:
            return False

        # Treat a landmark as an intermediate point when travelling through it
        # is almost as direct as drawing the source-target route itself.
        return source_leg + target_leg <= direct * 1.15

    @staticmethod
    def _segments_cross(
        a: CombatLandmark,
        b: CombatLandmark,
        c: CombatLandmark,
        d: CombatLandmark,
    ) -> bool:
        if {a.id, b.id} & {c.id, d.id}:
            return False
        assert a.x is not None and a.y is not None
        assert b.x is not None and b.y is not None
        assert c.x is not None and c.y is not None
        assert d.x is not None and d.y is not None

        def orientation(
            p: CombatLandmark,
            q: CombatLandmark,
            r: CombatLandmark,
        ) -> float:
            assert p.x is not None and p.y is not None
            assert q.x is not None and q.y is not None
            assert r.x is not None and r.y is not None
            return (
                (q.x - p.x) * (r.y - p.y)
                - (q.y - p.y) * (r.x - p.x)
            )

        ab_c = orientation(a, b, c)
        ab_d = orientation(a, b, d)
        cd_a = orientation(c, d, a)
        cd_b = orientation(c, d, b)
        epsilon = 1e-9
        return (
            ab_c * ab_d < -epsilon
            and cd_a * cd_b < -epsilon
        )

    @classmethod
    def _automatic_route_is_local(
        cls,
        source: CombatLandmark,
        target: CombatLandmark,
        landmarks: tuple[CombatLandmark, ...] | list[CombatLandmark],
    ) -> bool:
        if source.id == cls.CENTER_LANDMARK_ID or target.id == cls.CENTER_LANDMARK_ID:
            return False
        # Canvas geometry decides whether a shortcut is local, but generated
        # routes themselves always start as Close and can be adjusted by the DM.
        if cls._distance_between(source, target) > 0.60:
            return False
        return not any(
            cls._landmark_between(source, target, landmark)
            for landmark in landmarks
        )

    def auto_connect_landmark(
        self,
        guild_id: int,
        landmark_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        source = scene.landmark(landmark_id)
        if source is None:
            raise CombatError(f"Unknown combat landmark '{landmark_id}'.")
        if source.x is None or source.y is None:
            raise CombatError("Landmark must have a map position before auto-connect.")

        if source.id == self.CENTER_LANDMARK_ID:
            try:
                connected_ids = {
                    (
                        route.destination_landmark_id
                        if route.source_landmark_id == self.CENTER_LANDMARK_ID
                        else route.source_landmark_id
                    )
                    for route in scene.routes
                    if self.CENTER_LANDMARK_ID in {
                        route.source_landmark_id,
                        route.destination_landmark_id,
                    }
                }
                for target in scene.landmarks:
                    if (
                        target.id == self.CENTER_LANDMARK_ID
                        or target.id in connected_ids
                    ):
                        continue
                    self.repository.set_route(
                        scene.id,
                        self.CENTER_LANDMARK_ID,
                        target.id,
                        LandmarkDistance.CLOSE,
                        automatic=True,
                    )
            except ValueError as error:
                raise CombatError(str(error)) from error
            return self._require_current(guild_id)

        # Rebuild only this landmark's automatic local shortcuts. Manual routes
        # and the default center hub route remain untouched.
        self.repository.delete_automatic_routes_for_landmark(
            scene.id,
            landmark_id,
        )
        scene = self._require_current(guild_id)
        source = scene.landmark(landmark_id)
        assert source is not None

        has_center_route = any(
            {route.source_landmark_id, route.destination_landmark_id}
            == {self.CENTER_LANDMARK_ID, source.id}
            for route in scene.routes
        )
        if not has_center_route:
            try:
                self.repository.set_route(
                    scene.id,
                    self.CENTER_LANDMARK_ID,
                    source.id,
                    LandmarkDistance.CLOSE,
                    automatic=True,
                )
            except ValueError as error:
                raise CombatError(str(error)) from error
            scene = self._require_current(guild_id)
            source = scene.landmark(landmark_id)
            assert source is not None

        local_degree = sum(
            source.id in {
                route.source_landmark_id,
                route.destination_landmark_id,
            }
            and self.CENTER_LANDMARK_ID not in {
                route.source_landmark_id,
                route.destination_landmark_id,
            }
            for route in scene.routes
        )
        missing_local_connections = max(0, 2 - local_degree)
        if missing_local_connections == 0:
            return scene

        candidates = [
            landmark
            for landmark in scene.landmarks
            if (
                landmark.id != source.id
                and landmark.id != self.CENTER_LANDMARK_ID
                and landmark.x is not None
                and landmark.y is not None
                and self._automatic_route_is_local(
                    source,
                    landmark,
                    scene.landmarks,
                )
                and not any(
                    {route.source_landmark_id, route.destination_landmark_id}
                    == {source.id, landmark.id}
                    for route in scene.routes
                )
            )
        ]
        candidates.sort(
            key=lambda landmark: (
                self._distance_between(source, landmark),
                landmark.id,
            )
        )

        existing_segments = [
            (
                scene.landmark(route.source_landmark_id),
                scene.landmark(route.destination_landmark_id),
            )
            for route in scene.routes
        ]

        try:
            added = 0
            for target in candidates:
                if added >= missing_local_connections:
                    break
                if any(
                    first is not None
                    and second is not None
                    and self._segments_cross(source, target, first, second)
                    for first, second in existing_segments
                ):
                    continue
                self.repository.set_route(
                    scene.id,
                    source.id,
                    target.id,
                    LandmarkDistance.CLOSE,
                    automatic=True,
                )
                existing_segments.append((source, target))
                added += 1
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def auto_connect_all(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)

        # Auto-connect all is deterministic: rebuild only generated routes
        # while preserving every manual/default route.
        self.repository.delete_all_automatic_routes(scene.id)
        scene = self._require_current(guild_id)

        # Restore any missing spokes in the default center hub first.
        self.auto_connect_landmark(guild_id, self.CENTER_LANDMARK_ID)
        scene = self._require_current(guild_id)

        positioned = [
            landmark
            for landmark in scene.landmarks
            if (
                landmark.id != self.CENTER_LANDMARK_ID
                and landmark.x is not None
                and landmark.y is not None
            )
        ]
        local_degrees = {landmark.id: 0 for landmark in positioned}
        connected_pairs: set[frozenset[str]] = set()
        existing_segments: list[tuple[CombatLandmark, CombatLandmark]] = []

        for route in scene.routes:
            source = scene.landmark(route.source_landmark_id)
            target = scene.landmark(route.destination_landmark_id)
            if source is None or target is None:
                continue
            connected_pairs.add(frozenset((source.id, target.id)))
            existing_segments.append((source, target))
            if self.CENTER_LANDMARK_ID in {source.id, target.id}:
                continue
            if source.id in local_degrees:
                local_degrees[source.id] += 1
            if target.id in local_degrees:
                local_degrees[target.id] += 1

        candidates: list[
            tuple[float, str, str, CombatLandmark, CombatLandmark]
        ] = []
        for index, source in enumerate(positioned):
            for target in positioned[index + 1:]:
                pair = frozenset((source.id, target.id))
                if pair in connected_pairs:
                    continue
                if not self._automatic_route_is_local(
                    source,
                    target,
                    scene.landmarks,
                ):
                    continue
                candidates.append(
                    (
                        self._distance_between(source, target),
                        source.id,
                        target.id,
                        source,
                        target,
                    )
                )
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))

        try:
            for _, _, _, source, target in candidates:
                if (
                    local_degrees[source.id] >= 2
                    or local_degrees[target.id] >= 2
                ):
                    continue
                if any(
                    self._segments_cross(source, target, first, second)
                    for first, second in existing_segments
                ):
                    continue
                self.repository.set_route(
                    scene.id,
                    source.id,
                    target.id,
                    LandmarkDistance.CLOSE,
                    automatic=True,
                )
                local_degrees[source.id] += 1
                local_degrees[target.id] += 1
                existing_segments.append((source, target))
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
