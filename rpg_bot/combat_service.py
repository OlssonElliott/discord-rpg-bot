"""Application service for landmark-based combat scene state."""

import math

from .combat import (
    CombatLandmark,
    CombatScene,
    CombatantKind,
    CombatantState,
    LandmarkDistance,
    LandmarkRelation,
)
from .combat_repository import CombatRepository
from .database import Database
from .world_service import WorldService


class CombatError(ValueError):
    """Raised when a combat scene mutation is not valid."""


class CombatService:
    """UI-independent combat scene orchestration."""

    CENTER_LANDMARK_ID = "room:center"

    def __init__(self, database: Database) -> None:
        self.database = database
        self.world = WorldService(database)
        self.repository = CombatRepository(database.path)
        self.repository.initialize()

    def start(self, guild_id: int, room_id: str) -> CombatScene:
        if self.repository.get_active_scene(guild_id) is not None:
            raise CombatError("This server already has an active combat scene.")

        room = self.world.get_room(room_id)
        if room is None:
            raise CombatError(f"Room '{room_id}' does not exist.")

        landmarks = [
            CombatLandmark(
                self.CENTER_LANDMARK_ID,
                "Room Center",
                "A neutral anchor for combatants before the scene layout is arranged.",
                synthetic=True,
                x=0.5,
                y=0.5,
            )
        ]
        landmarks.extend(
            CombatLandmark(
                id=f"feature:{feature.id}",
                name=feature.name,
                description=feature.description,
                source_feature_id=feature.id,
                feature_type=feature.feature_type.value,
            )
            for feature in self.world.list_room_features(room_id)
        )

        combatants = [
            CombatantState(
                CombatantKind.CHARACTER,
                str(character.character_id),
                character.name,
                self.CENTER_LANDMARK_ID,
            )
            for character in room.characters
            if character.character_id is not None
        ]
        combatants.extend(
            CombatantState(
                CombatantKind.ENEMY,
                enemy.id,
                enemy.name,
                self.CENTER_LANDMARK_ID,
            )
            for enemy in room.enemies
        )

        try:
            return self.repository.start_scene(
                guild_id,
                room_id,
                tuple(landmarks),
                tuple(combatants),
            )
        except ValueError as error:
            raise CombatError(str(error)) from error

    def current(self, guild_id: int) -> CombatScene | None:
        return self.repository.get_active_scene(guild_id)

    def end(self, guild_id: int) -> CombatScene:
        scene = self.repository.end_scene(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene

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
        if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1) or not (0 <= y <= 1):
            raise CombatError("Landmark coordinates must be normalized between 0 and 1.")
        scene = self._require_current(guild_id)
        try:
            self.repository.set_landmark_position(scene.id, landmark_id, x, y)
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def connect_landmarks(
        self,
        guild_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
        distance: LandmarkDistance | str,
        *,
        obstacle: str | None = None,
        blocked: bool = False,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        try:
            parsed_distance = (
                distance
                if isinstance(distance, LandmarkDistance)
                else LandmarkDistance(distance)
            )
            self.repository.set_route(
                scene.id,
                source_landmark_id,
                destination_landmark_id,
                parsed_distance,
                obstacle=obstacle.strip() if obstacle and obstacle.strip() else None,
                blocked=blocked,
            )
        except ValueError as error:
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
        scene = self._require_current(guild_id)
        try:
            parsed_kind = kind if isinstance(kind, CombatantKind) else CombatantKind(kind)
            parsed_relation = (
                relation
                if isinstance(relation, LandmarkRelation)
                else LandmarkRelation(relation)
            )
            self.repository.set_combatant_position(
                scene.id,
                parsed_kind,
                source_id,
                landmark_id,
                parsed_relation,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def _require_current(self, guild_id: int) -> CombatScene:
        scene = self.current(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene
