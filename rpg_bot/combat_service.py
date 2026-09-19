"""Application service for landmark-based combat scene state."""

import math
import re

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
from .dungeon import ConnectionType
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

        door_specs: list[tuple[object, str, str, str | None]] = []
        for connection in self.world.area_graph(room.area_id).connections:
            if connection.connection_type is not ConnectionType.DOOR:
                continue
            if connection.source_room_id == room_id:
                exit_name = connection.exit_name
                adjacent_room_id = connection.destination_room_id
            elif connection.bidirectional and connection.destination_room_id == room_id:
                exit_name = connection.return_exit_name or connection.exit_name
                adjacent_room_id = connection.source_room_id
            else:
                continue
            door_specs.append(
                (
                    connection,
                    exit_name,
                    adjacent_room_id,
                    self._cardinal_direction(exit_name),
                )
            )

        direction_counts: dict[str, int] = {}
        for _, _, _, direction in door_specs:
            if direction is not None:
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
        direction_indices: dict[str, int] = {}
        door_landmark_ids: list[str] = []

        for connection, exit_name, adjacent_room_id, direction in door_specs:
            adjacent_room = self.world.get_room(adjacent_room_id)
            connection_key = connection.connection_id or f"{room_id}:{len(landmarks)}"
            landmark_id = f"door:{connection_key}"
            x = None
            y = None
            if direction is not None:
                index = direction_indices.get(direction, 0)
                direction_indices[direction] = index + 1
                x, y = self._door_position(
                    direction,
                    index,
                    direction_counts[direction],
                )
            landmarks.append(
                CombatLandmark(
                    id=landmark_id,
                    name=f"Door: {exit_name}",
                    description=(
                        f"Exit to "
                        f"{adjacent_room.name if adjacent_room is not None else adjacent_room_id}."
                    ),
                    source_connection_id=connection.connection_id,
                    feature_type="door",
                    x=x,
                    y=y,
                )
            )
            door_landmark_ids.append(landmark_id)

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
            scene = self.repository.start_scene(
                guild_id,
                room_id,
                tuple(landmarks),
                tuple(combatants),
            )
            for landmark_id in door_landmark_ids:
                self.repository.set_route(
                    scene.id,
                    self.CENTER_LANDMARK_ID,
                    landmark_id,
                    LandmarkDistance.CLOSE,
                )
            return self._require_current(guild_id)
        except ValueError as error:
            raise CombatError(str(error)) from error

    @staticmethod
    def _cardinal_direction(exit_name: str) -> str | None:
        aliases = {
            "n": "north",
            "north": "north",
            "e": "east",
            "east": "east",
            "s": "south",
            "south": "south",
            "w": "west",
            "west": "west",
        }
        directions = {
            aliases[token]
            for token in re.findall(r"[a-z]+", exit_name.casefold())
            if token in aliases
        }
        return next(iter(directions)) if len(directions) == 1 else None

    @staticmethod
    def _door_position(
        direction: str,
        index: int,
        count: int,
    ) -> tuple[float, float]:
        if count <= 1:
            offset = 0.0
        else:
            step = min(0.12, 0.48 / (count - 1))
            offset = (index - (count - 1) / 2) * step

        if direction == "north":
            return 0.5 + offset, 0.08
        if direction == "east":
            return 0.82, 0.5 + offset
        if direction == "south":
            return 0.5 + offset, 0.82
        return 0.08, 0.5 + offset

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
