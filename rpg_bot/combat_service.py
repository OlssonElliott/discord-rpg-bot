"""Application service for landmark-based combat scene state."""

from dataclasses import replace
import math
import random
import re
from uuid import uuid4

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
    _LANDMARK_LAYOUT_SLOTS = (
        (0.12, 0.18),
        (0.80, 0.18),
        (0.12, 0.82),
        (0.80, 0.82),
        (0.12, 0.34),
        (0.32, 0.18),
        (0.60, 0.18),
        (0.80, 0.34),
        (0.12, 0.66),
        (0.32, 0.82),
        (0.60, 0.82),
        (0.80, 0.66),
        (0.32, 0.34),
        (0.60, 0.34),
        (0.32, 0.66),
        (0.60, 0.66),
    )

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

        occupied_landmarks = [
            landmark
            for landmark in landmarks
            if landmark.x is not None and landmark.y is not None
        ]
        positioned_landmarks: list[CombatLandmark] = []
        for landmark in landmarks:
            if landmark.x is None or landmark.y is None:
                x, y = self._next_open_position(occupied_landmarks)
                landmark = replace(landmark, x=x, y=y)
                occupied_landmarks.append(landmark)
            positioned_landmarks.append(landmark)
        landmarks = positioned_landmarks

        combatants: list[CombatantState] = []
        for character in room.characters:
            if character.character_id is None:
                continue
            initiative_roll, initiative_score = self._roll_initiative(
                self._character_insight_modifier(character.character_id)
            )
            combatants.append(
                CombatantState(
                    CombatantKind.CHARACTER,
                    str(character.character_id),
                    character.name,
                    self.CENTER_LANDMARK_ID,
                    LandmarkRelation.AT,
                    initiative_roll,
                    initiative_score,
                )
            )

        for enemy in room.enemies:
            initiative_roll, initiative_score = self._roll_initiative(
                self._enemy_insight_modifier(enemy.id)
            )
            combatants.append(
                CombatantState(
                    CombatantKind.ENEMY,
                    enemy.id,
                    enemy.name,
                    self.CENTER_LANDMARK_ID,
                    LandmarkRelation.AT,
                    initiative_roll,
                    initiative_score,
                )
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
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "combat_started",
                f"Combat started in {room.name}.",
            )
            current = self._require_current(guild_id)
            current_combatant = current.current_combatant()
            if current_combatant is not None:
                self.repository.append_log(
                    current.id,
                    current.round_number,
                    "turn_started",
                    f"{current_combatant.name}'s turn began.",
                    actor_kind=current_combatant.kind,
                    actor_source_id=current_combatant.source_id,
                    actor_name=current_combatant.name,
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

    @classmethod
    def _next_open_position(
        cls,
        landmarks: list[CombatLandmark] | tuple[CombatLandmark, ...],
    ) -> tuple[float, float]:
        occupied = [
            (landmark.x, landmark.y)
            for landmark in landmarks
            if landmark.x is not None and landmark.y is not None
        ]

        def is_free(candidate: tuple[float, float]) -> bool:
            x, y = candidate
            return all(
                abs(x - occupied_x) >= 0.20 or abs(y - occupied_y) >= 0.14
                for occupied_x, occupied_y in occupied
            )

        for candidate in cls._LANDMARK_LAYOUT_SLOTS:
            if is_free(candidate):
                return candidate

        # Very crowded scenes still get a deterministic position instead of
        # failing to start. The normal slots above cover ordinary room layouts.
        return max(
            cls._LANDMARK_LAYOUT_SLOTS,
            key=lambda candidate: min(
                (
                    abs(candidate[0] - occupied_x) / 0.20
                    + abs(candidate[1] - occupied_y) / 0.14
                    for occupied_x, occupied_y in occupied
                ),
                default=float("inf"),
            ),
        )

    @staticmethod
    def _roll_initiative(insight_modifier: int) -> tuple[int, int]:
        roll = random.randint(1, 20)
        return roll, roll + insight_modifier

    def _character_insight_modifier(self, character_id: int) -> int:
        insight = self.database.get_character_attribute(character_id, "insight")
        return (insight - 10) // 2

    def _enemy_insight_modifier(self, enemy_id: str) -> int:
        enemy = self.world.get_enemy(enemy_id)
        if enemy is None:
            return 0
        template = self.world.get_enemy_template(enemy.template_id)
        return template.insight if template is not None else 0

    @staticmethod
    def _turn_index(scene: CombatScene) -> int | None:
        ordered = scene.initiative_order()
        for index, combatant in enumerate(ordered):
            if (
                combatant.kind is scene.current_turn_kind
                and combatant.source_id == scene.current_turn_source_id
            ):
                return index
        return None

    def _ensure_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if scene.current_combatant() is not None or not scene.combatants:
            return scene
        available = [
            combatant
            for combatant in scene.initiative_order()
            if not combatant.acted_this_round
        ]
        if not available:
            self.repository.set_all_combatants_acted(scene.id, False)
            scene = self._require_current(guild_id)
            available = list(scene.initiative_order())
        first = available[0]
        try:
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                first.kind,
                first.source_id,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "turn_started",
                f"{first.name}'s turn began.",
                actor_kind=first.kind,
                actor_source_id=first.source_id,
                actor_name=first.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def current(self, guild_id: int) -> CombatScene | None:
        return self.repository.get_active_scene(guild_id)

    def end(self, guild_id: int) -> CombatScene:
        current = self._require_current(guild_id)
        self.repository.append_log(
            current.id,
            current.round_number,
            "combat_ended",
            "Combat ended.",
        )
        scene = self.repository.end_scene(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene

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
            candidate = CombatantState(
                CombatantKind.ENEMY,
                enemy.id,
                enemy.name,
                destination_id,
                LandmarkRelation.AT,
                initiative_roll,
                initiative_score,
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

                available = [
                    combatant
                    for combatant in remaining_scene.initiative_order()
                    if not combatant.acted_this_round
                ]
                next_round = scene.round_number
                if not available:
                    self.repository.set_all_combatants_acted(scene.id, False)
                    next_round += 1
                    remaining_scene = self._require_current(guild_id)
                    available = list(remaining_scene.initiative_order())

                next_combatant = available[0]
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
        return self._ensure_turn(guild_id)

    def next_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if not scene.combatants:
            return scene
        current = scene.current_combatant()
        if current is None:
            return self._ensure_turn(guild_id)

        try:
            self.repository.set_combatant_acted(
                scene.id,
                current.kind,
                current.source_id,
                True,
            )
            updated = self._require_current(guild_id)
            available = [
                combatant
                for combatant in updated.initiative_order()
                if not combatant.acted_this_round
            ]
            next_round = scene.round_number
            if not available:
                self.repository.set_all_combatants_acted(scene.id, False)
                next_round += 1
                updated = self._require_current(guild_id)
                available = list(updated.initiative_order())

            target = available[0]
            self.repository.set_turn(
                scene.id,
                next_round,
                target.kind,
                target.source_id,
            )
            self.repository.append_log(
                scene.id,
                next_round,
                "turn_started",
                f"{target.name}'s turn began.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def previous_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if not scene.combatants:
            return scene
        if scene.current_combatant() is None:
            return self._ensure_turn(guild_id)

        ordered = scene.initiative_order()
        current_index = self._turn_index(scene)
        assert current_index is not None
        previous_index = (current_index - 1) % len(ordered)
        target = ordered[previous_index]
        previous_round = scene.round_number
        try:
            if current_index == 0 and scene.round_number > 1:
                previous_round -= 1
                self.repository.set_all_combatants_acted(scene.id, True)
            self.repository.set_combatant_acted(
                scene.id,
                target.kind,
                target.source_id,
                False,
            )
            self.repository.set_turn(
                scene.id,
                previous_round,
                target.kind,
                target.source_id,
            )
            self.repository.append_log(
                scene.id,
                previous_round,
                "turn_rewound",
                f"DM moved the turn back to {target.name}.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except ValueError as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def jump_turn(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            target = next(
                combatant
                for combatant in scene.combatants
                if combatant.kind is parsed_kind
                and combatant.source_id == source_id
            )
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                parsed_kind,
                source_id,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "turn_changed",
                f"DM set the current turn to {target.name}.",
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

    def set_initiative(
        self,
        guild_id: int,
        kind: CombatantKind | str,
        source_id: str,
        initiative_score: int,
    ) -> CombatScene:
        if (
            isinstance(initiative_score, bool)
            or not isinstance(initiative_score, int)
        ):
            raise CombatError("Initiative must be a whole number.")
        scene = self._require_current(guild_id)
        try:
            parsed_kind = (
                kind
                if isinstance(kind, CombatantKind)
                else CombatantKind(kind)
            )
            target = next(
                combatant
                for combatant in scene.combatants
                if combatant.kind is parsed_kind
                and combatant.source_id == source_id
            )
            self.repository.set_initiative(
                scene.id,
                parsed_kind,
                source_id,
                initiative_score,
            )
            self.repository.append_log(
                scene.id,
                scene.round_number,
                "initiative_changed",
                (
                    f"{target.name}'s initiative changed from "
                    f"{target.initiative_score} to {initiative_score}."
                ),
                actor_kind=target.kind,
                actor_source_id=target.source_id,
                actor_name=target.name,
            )
        except (ValueError, StopIteration) as error:
            raise CombatError(str(error)) from error
        return self._require_current(guild_id)

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
        x, y = self._next_open_position(scene.landmarks)
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
        return self._require_current(guild_id)

    def disconnect_landmarks(
        self,
        guild_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
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
            combatant = next(
                item
                for item in scene.combatants
                if item.kind is parsed_kind and item.source_id == source_id
            )
            landmark = scene.landmark(landmark_id)
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

    def _require_current(self, guild_id: int) -> CombatScene:
        scene = self.current(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene
