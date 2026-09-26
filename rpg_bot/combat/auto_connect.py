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

        # Two nearest-neighbour spacings comfortably includes local diagonals
        # while the upper bound prevents accidental cross-room shortcuts.
        return min(
            0.90,
            max(0.18, median(nearest_distances) * 2.0),
        )

    @staticmethod
    def _direction_sector(
        source: CombatLandmark,
        target: CombatLandmark,
    ) -> int:
        assert source.x is not None and source.y is not None
        assert target.x is not None and target.y is not None
        angle = math.atan2(
            target.y - source.y,
            target.x - source.x,
        )
        return round(angle / (math.pi / 4)) % 8

    @classmethod
    def _automatic_pairs(
        cls,
        scene: CombatScene,
    ) -> list[tuple[CombatLandmark, CombatLandmark]]:
        """Build a sparse local graph from nearest neighbours in 8 directions.

        This naturally creates horizontal, vertical and diagonal movement links
        without assigning any semantic role to particular landmarks.
        """
        positioned = [
            landmark
            for landmark in scene.landmarks
            if landmark.x is not None and landmark.y is not None
        ]
        radius = cls._connection_radius(positioned)
        if radius <= 0:
            return []

        pairs: dict[
            frozenset[str],
            tuple[float, CombatLandmark, CombatLandmark],
        ] = {}

        for source in positioned:
            nearest_by_sector: dict[
                int,
                tuple[float, str, CombatLandmark],
            ] = {}

            for target in positioned:
                if target.id == source.id:
                    continue
                distance = cls._distance_between(source, target)
                if distance <= 0 or distance > radius:
                    continue

                sector = cls._direction_sector(source, target)
                candidate = (distance, target.id, target)
                current = nearest_by_sector.get(sector)
                if current is None or candidate[:2] < current[:2]:
                    nearest_by_sector[sector] = candidate

            for distance, _, target in nearest_by_sector.values():
                key = frozenset((source.id, target.id))
                existing = pairs.get(key)
                if existing is None or distance < existing[0]:
                    pairs[key] = (distance, source, target)

        ordered = sorted(
            pairs.values(),
            key=lambda item: (
                item[0],
                min(item[1].id, item[2].id),
                max(item[1].id, item[2].id),
            ),
        )
        return [
            (source, target)
            for _, source, target in ordered
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
                    LandmarkDistance.NEAR,
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
                    LandmarkDistance.NEAR,
                    automatic=True,
                )
                connected_pairs.add(pair)
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id)
