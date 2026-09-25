"""Automatic combat route generation and spatial heuristics."""

from __future__ import annotations

import math

from .errors import CombatError
from .models import CombatLandmark, CombatScene, LandmarkDistance


class CombatAutoConnectMixin:
    """Generate local combat routes from landmark geometry."""

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
        return ab_c * ab_d < -epsilon and cd_a * cd_b < -epsilon

    @classmethod
    def _automatic_route_is_local(
        cls,
        source: CombatLandmark,
        target: CombatLandmark,
        landmarks: tuple[CombatLandmark, ...] | list[CombatLandmark],
    ) -> bool:
        if source.id == cls.CENTER_LANDMARK_ID or target.id == cls.CENTER_LANDMARK_ID:
            return False
        if cls._distance_between(source, target) > 0.60:
            return False
        return not any(
            cls._landmark_between(source, target, landmark)
            for landmark in landmarks
        )

    @classmethod
    def _corner_shortcut_pairs(
        cls,
        scene: CombatScene,
    ) -> list[tuple[CombatLandmark, CombatLandmark]]:
        """Return one local diagonal around each synthetic room corner."""
        center = scene.landmark(cls.CENTER_LANDMARK_ID)
        if center is None or center.x is None or center.y is None:
            return []

        candidates = [
            landmark
            for landmark in scene.landmarks
            if (
                landmark.id != cls.CENTER_LANDMARK_ID
                and landmark.feature_type != "corner"
                and landmark.x is not None
                and landmark.y is not None
            )
        ]
        pairs: dict[
            frozenset[str],
            tuple[CombatLandmark, CombatLandmark],
        ] = {}

        for corner in scene.landmarks:
            if (
                corner.feature_type != "corner"
                or corner.x is None
                or corner.y is None
            ):
                continue

            horizontal_sign = 1 if corner.x < center.x else -1
            vertical_sign = 1 if corner.y < center.y else -1
            horizontal: list[
                tuple[float, float, str, CombatLandmark]
            ] = []
            vertical: list[
                tuple[float, float, str, CombatLandmark]
            ] = []

            for landmark in candidates:
                assert landmark.x is not None and landmark.y is not None
                dx = landmark.x - corner.x
                dy = landmark.y - corner.y
                distance = cls._distance_between(corner, landmark)
                if distance > 0.55:
                    continue

                if dx * horizontal_sign > 0 and abs(dx) >= abs(dy):
                    horizontal.append(
                        (abs(dy), distance, landmark.id, landmark)
                    )
                if dy * vertical_sign > 0 and abs(dy) >= abs(dx):
                    vertical.append(
                        (abs(dx), distance, landmark.id, landmark)
                    )

            if not horizontal or not vertical:
                continue

            horizontal.sort(key=lambda item: (item[0], item[1], item[2]))
            vertical.sort(key=lambda item: (item[0], item[1], item[2]))
            first = horizontal[0][3]
            second = vertical[0][3]

            if first.id == second.id:
                second = next(
                    (
                        item[3]
                        for item in vertical[1:]
                        if item[3].id != first.id
                    ),
                    second,
                )
            if first.id == second.id:
                continue
            if cls._distance_between(first, second) > 0.65:
                continue

            pair = frozenset((first.id, second.id))
            pairs[pair] = (first, second)

        return [
            pairs[pair]
            for pair in sorted(
                pairs,
                key=lambda item: tuple(sorted(item)),
            )
        ]

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

        connected_pairs = {
            frozenset(
                (
                    route.source_landmark_id,
                    route.destination_landmark_id,
                )
            )
            for route in scene.routes
        }
        existing_segments = [
            (
                scene.landmark(route.source_landmark_id),
                scene.landmark(route.destination_landmark_id),
            )
            for route in scene.routes
            if self.CENTER_LANDMARK_ID not in {
                route.source_landmark_id,
                route.destination_landmark_id,
            }
        ]

        try:
            if missing_local_connections:
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
                        and frozenset((source.id, landmark.id))
                        not in connected_pairs
                    )
                ]
                candidates.sort(
                    key=lambda landmark: (
                        self._distance_between(source, landmark),
                        landmark.id,
                    )
                )

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
                    connected_pairs.add(frozenset((source.id, target.id)))
                    existing_segments.append((source, target))
                    added += 1

            for first, second in self._corner_shortcut_pairs(scene):
                if source.id not in {first.id, second.id}:
                    continue
                pair = frozenset((first.id, second.id))
                if pair in connected_pairs:
                    continue
                self.repository.set_route(
                    scene.id,
                    first.id,
                    second.id,
                    LandmarkDistance.CLOSE,
                    automatic=True,
                )
                connected_pairs.add(pair)
                existing_segments.append((first, second))
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def auto_connect_all(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        self.repository.delete_all_automatic_routes(scene.id)
        scene = self._require_current(guild_id)

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
            if self.CENTER_LANDMARK_ID in {source.id, target.id}:
                continue
            existing_segments.append((source, target))
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
                connected_pairs.add(frozenset((source.id, target.id)))
                existing_segments.append((source, target))

            for source, target in self._corner_shortcut_pairs(scene):
                pair = frozenset((source.id, target.id))
                if pair in connected_pairs:
                    continue
                self.repository.set_route(
                    scene.id,
                    source.id,
                    target.id,
                    LandmarkDistance.CLOSE,
                    automatic=True,
                )
                connected_pairs.add(pair)
                existing_segments.append((source, target))
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)
