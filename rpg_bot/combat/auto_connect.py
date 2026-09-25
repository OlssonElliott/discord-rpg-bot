"""Automatic combat route generation from landmark geometry."""

from __future__ import annotations

import math
from statistics import median

from .errors import CombatError
from .models import CombatLandmark, CombatScene, LandmarkDistance


class CombatAutoConnectMixin:
    """Generate local combat routes without assuming landmark roles or IDs."""

    @staticmethod
    def _distance_between(
        source: CombatLandmark,
        target: CombatLandmark,
    ) -> float:
        assert source.x is not None and source.y is not None
        assert target.x is not None and target.y is not None
        return math.hypot(target.x - source.x, target.y - source.y)

    @classmethod
    def _connection_radius(
        cls,
        landmarks: list[CombatLandmark],
    ) -> float:
        """Derive a local-neighbour radius from the scene itself."""
        if len(landmarks) < 2:
            return 0.0

        nearest_distances: list[float] = []
        for source in landmarks:
            distances = [
                cls._distance_between(source, target)
                for target in landmarks
                if target.id != source.id
            ]
            if distances:
                nearest_distances.append(min(distances))

        if not nearest_distances:
            return 0.0

        # Large enough to include the diagonal of a regular local cell while
        # remaining tied to this scene's actual landmark spacing.
        return max(0.12, median(nearest_distances) * 1.6)

    @classmethod
    def _gabriel_neighbours(
        cls,
        source: CombatLandmark,
        target: CombatLandmark,
        landmarks: list[CombatLandmark],
        radius: float,
    ) -> bool:
        """Return whether source-target is an unobstructed local graph edge.

        Gabriel-graph geometry gives us cardinal and useful diagonal links
        without knowing whether a landmark is a corner, center, door, etc.
        """
        distance = cls._distance_between(source, target)
        if distance <= 0 or distance > radius:
            return False

        assert source.x is not None and source.y is not None
        assert target.x is not None and target.y is not None
        midpoint_x = (source.x + target.x) / 2
        midpoint_y = (source.y + target.y) / 2
        radius_squared = (distance / 2) ** 2
        epsilon = 1e-9

        for candidate in landmarks:
            if (
                candidate.id in {source.id, target.id}
                or candidate.x is None
                or candidate.y is None
            ):
                continue
            candidate_distance_squared = (
                (candidate.x - midpoint_x) ** 2
                + (candidate.y - midpoint_y) ** 2
            )
            if candidate_distance_squared < radius_squared - epsilon:
                return False

        return True

    @classmethod
    def _automatic_pairs(
        cls,
        scene: CombatScene,
    ) -> list[tuple[CombatLandmark, CombatLandmark]]:
        positioned = [
            landmark
            for landmark in scene.landmarks
            if landmark.x is not None and landmark.y is not None
        ]
        radius = cls._connection_radius(positioned)
        candidates: list[
            tuple[float, str, str, CombatLandmark, CombatLandmark]
        ] = []

        for index, source in enumerate(positioned):
            for target in positioned[index + 1:]:
                if not cls._gabriel_neighbours(
                    source,
                    target,
                    positioned,
                    radius,
                ):
                    continue
                candidates.append(
                    (
                        cls._distance_between(source, target),
                        source.id,
                        target.id,
                        source,
                        target,
                    )
                )

        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return [
            (source, target)
            for _, _, _, source, target in candidates
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
            raise CombatError(
                "Landmark must have a map position before auto-connect."
            )

        # Only generated routes touching this landmark are rebuilt. Manual
        # routes remain authoritative.
        self.repository.delete_automatic_routes_for_landmark(
            scene.id,
            landmark_id,
        )
        scene = self._require_current(guild_id)

        connected_pairs = {
            frozenset(
                (
                    route.source_landmark_id,
                    route.destination_landmark_id,
                )
            )
            for route in scene.routes
        }

        try:
            for first, second in self._automatic_pairs(scene):
                if landmark_id not in {first.id, second.id}:
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
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id)

    def auto_connect_all(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)

        # Deterministically rebuild generated topology while preserving every
        # route the DM created or edited manually.
        self.repository.delete_all_automatic_routes(scene.id)
        scene = self._require_current(guild_id)

        connected_pairs = {
            frozenset(
                (
                    route.source_landmark_id,
                    route.destination_landmark_id,
                )
            )
            for route in scene.routes
        }

        try:
            for source, target in self._automatic_pairs(scene):
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
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id)
