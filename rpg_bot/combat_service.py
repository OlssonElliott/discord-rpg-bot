"""Application service for landmark-based combat scene state."""

from dataclasses import replace
import heapq
import math
import random
import re
from uuid import uuid4

from .combat import (
    AttackResult,
    CombatLandmark,
    CombatRoute,
    CombatScene,
    CombatantKind,
    CombatantState,
    DamageRoll,
    DeathSaveResult,
    EnemyAttackResult,
    LandmarkDistance,
    LandmarkRelation,
)
from .combat_repository import CombatRepository
from .database import Database
from .dungeon import ConnectionType
from .enemies import EnemyStatus
from .inventory import DamagePart, EquipmentSlot, ItemTemplate, ItemType
from .models import CharacterCombatStatus
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
            character_state = self.database.get_character_combat_state(
                character.character_id
            )
            if character_state.status in {
                CharacterCombatStatus.STABLE,
                CharacterCombatStatus.DEAD,
            }:
                continue
            initiative_roll, initiative_score = self._roll_initiative(
                self._character_insight_modifier(character.character_id)
            )
            movement_budget = self._character_movement_budget(
                character.character_id
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
                    movement_budget=movement_budget,
                    movement_remaining=movement_budget,
                )
            )

        for enemy in room.enemies:
            enemy_instance = self.world.get_enemy(enemy.id)
            if (
                enemy_instance is not None
                and enemy_instance.status is not EnemyStatus.ACTIVE
            ):
                continue
            initiative_roll, initiative_score = self._roll_initiative(
                self._enemy_insight_modifier(enemy.id)
            )
            movement_budget = self._enemy_movement_budget(enemy.id)
            combatants.append(
                CombatantState(
                    CombatantKind.ENEMY,
                    enemy.id,
                    enemy.name,
                    self.CENTER_LANDMARK_ID,
                    LandmarkRelation.AT,
                    initiative_roll,
                    initiative_score,
                    movement_budget=movement_budget,
                    movement_remaining=movement_budget,
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
            return self._resolve_current_death_save(guild_id)
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

    def _character_movement_budget(self, character_id: int) -> int:
        strength = self.database.get_character_attribute(
            character_id,
            "strength",
        )
        return max(1, 3 + (strength - 10) // 2)

    def _enemy_movement_budget(self, enemy_id: str) -> int:
        enemy = self.world.get_enemy(enemy_id)
        if enemy is None:
            return 3
        template = self.world.get_enemy_template(enemy.template_id)
        return max(
            1,
            3 + (template.strength if template is not None else 0),
        )

    def _character_by_source_id(self, source_id: str):
        try:
            character_id = int(source_id)
        except ValueError as error:
            raise CombatError(
                f"Character combatant '{source_id}' is invalid."
            ) from error
        character = next(
            (
                candidate
                for candidate in self.database.list_all_characters()
                if candidate.character_id == character_id
            ),
            None,
        )
        if character is None:
            raise CombatError(
                f"Character {character_id} does not exist."
            )
        return character

    def _combatant_can_take_turn(
        self,
        combatant: CombatantState,
    ) -> bool:
        if combatant.kind is CombatantKind.ENEMY:
            return True
        try:
            character_id = int(combatant.source_id)
        except ValueError:
            return False
        state = self.database.get_character_combat_state(character_id)
        return state.status not in {
            CharacterCombatStatus.STABLE,
            CharacterCombatStatus.DEAD,
        }

    def _available_turn_combatants(
        self,
        scene: CombatScene,
    ) -> list[CombatantState]:
        return [
            combatant
            for combatant in scene.initiative_order()
            if not combatant.acted_this_round
            and self._combatant_can_take_turn(combatant)
        ]

    @staticmethod
    def _roll_d20(
        *,
        disadvantage: bool = False,
    ) -> tuple[tuple[int, ...], int]:
        rolls = tuple(
            random.randint(1, 20)
            for _ in range(2 if disadvantage else 1)
        )
        return rolls, min(rolls) if disadvantage else rolls[0]

    def _equipped_attack_weapon(
        self,
        character_id: int,
    ) -> ItemTemplate | None:
        inventory = self.database.get_character_inventory(character_id)
        for slot in (EquipmentSlot.MAIN_HAND, EquipmentSlot.OFF_HAND):
            instance_id = inventory.equipment.get(slot)
            if instance_id is None:
                continue
            instance = next(
                (
                    item
                    for item in inventory.items
                    if item.instance_id == instance_id
                ),
                None,
            )
            if instance is None or instance.durability == 0:
                continue
            try:
                template = self.world.catalog.get(instance.template_id)
            except ValueError:
                continue
            if template.item_type is ItemType.WEAPON:
                return template
        return None

    @staticmethod
    def _weapon_attack_attribute(
        weapon: ItemTemplate | None,
    ) -> str:
        if weapon is None:
            return "strength"
        tags = {tag.casefold() for tag in weapon.tags}
        if tags & {"magic", "spell", "focus", "staff"}:
            return "arcana"
        if tags & {
            "bow",
            "crossbow",
            "ranged",
            "finesse",
            "dagger",
            "light",
        }:
            return "dexterity"
        return "strength"

    def _equipped_armor_stats(
        self,
        character_id: int,
    ) -> tuple[int, int]:
        inventory = self.database.get_character_inventory(character_id)
        armor_id = inventory.equipment.get(EquipmentSlot.ARMOR)
        if armor_id is None:
            return 0, 0
        try:
            instance = inventory.item(armor_id)
            template = self.world.catalog.get(instance.template_id)
        except ValueError:
            return 0, 0
        if template.item_type is not ItemType.ARMOR:
            return 0, 0
        protection = (
            instance.durability
            if instance.durability is not None
            else template.protection or 0
        )
        return max(0, protection), template.dodge_penalty

    def _automatic_defense(
        self,
        character_id: int,
    ) -> tuple[str, str, int]:
        _, dodge_penalty = self._equipped_armor_stats(character_id)
        strength = self.database.get_character_attribute(
            character_id,
            "strength",
        )
        dexterity = self.database.get_character_attribute(
            character_id,
            "dexterity",
        )
        arcana = self.database.get_character_attribute(
            character_id,
            "arcana",
        )
        options = (
            ("guard", "strength", (strength - 10) // 2),
            (
                "dodge",
                "dexterity",
                (dexterity - 10) // 2 + dodge_penalty,
            ),
            ("arcane_defense", "arcana", (arcana - 10) // 2),
        )
        return max(options, key=lambda option: option[2])

    @staticmethod
    def _roll_damage_expression(
        expression: str,
    ) -> tuple[tuple[int, ...], int]:
        match = re.fullmatch(
            r"\s*(\d*)d(\d+)([+-]\d+)?\s*",
            expression.casefold(),
        )
        if match is None:
            raise CombatError(
                f"Unsupported enemy damage expression '{expression}'."
            )
        count = int(match.group(1) or "1")
        die = int(match.group(2))
        bonus = int(match.group(3) or "0")
        if count < 1 or die < 1:
            raise CombatError(
                f"Unsupported enemy damage expression '{expression}'."
            )
        rolls = tuple(random.randint(1, die) for _ in range(count))
        return rolls, max(0, sum(rolls) + bonus)

    @staticmethod
    def _same_combat_position(
        first: CombatantState,
        second: CombatantState,
    ) -> bool:
        if first.is_between_landmarks != second.is_between_landmarks:
            return False
        if not first.is_between_landmarks:
            return first.landmark_id == second.landmark_id

        first_ids = {
            first.route_source_landmark_id,
            first.route_destination_landmark_id,
        }
        second_ids = {
            second.route_source_landmark_id,
            second.route_destination_landmark_id,
        }
        if first_ids != second_ids or first.route_cost != second.route_cost:
            return False

        canonical_start = min(
            first.route_source_landmark_id or "",
            first.route_destination_landmark_id or "",
        )
        first_progress = (
            first.route_progress
            if first.route_source_landmark_id == canonical_start
            else first.route_cost - first.route_progress
        )
        second_progress = (
            second.route_progress
            if second.route_source_landmark_id == canonical_start
            else second.route_cost - second.route_progress
        )
        return first_progress == second_progress

    @staticmethod
    def _route_between(
        scene: CombatScene,
        first_landmark_id: str,
        second_landmark_id: str,
    ) -> CombatRoute | None:
        route_ids = {first_landmark_id, second_landmark_id}
        return next(
            (
                route
                for route in scene.routes
                if {
                    route.source_landmark_id,
                    route.destination_landmark_id,
                } == route_ids
            ),
            None,
        )

    @classmethod
    def _path_cost(
        cls,
        scene: CombatScene,
        path: tuple[str, ...],
    ) -> int:
        total = 0
        for source_id, destination_id in zip(path, path[1:]):
            route = cls._route_between(
                scene,
                source_id,
                destination_id,
            )
            if route is None:
                raise CombatError(
                    "Combat route changed while movement was resolved."
                )
            total += route.movement_cost
        return total

    @classmethod
    def _shortest_path(
        cls,
        scene: CombatScene,
        start_landmark_id: str,
        destination_landmark_id: str,
    ) -> tuple[str, ...] | None:
        if start_landmark_id == destination_landmark_id:
            return (start_landmark_id,)

        neighbours: dict[str, list[tuple[str, int]]] = {}
        for route in scene.routes:
            if route.blocked:
                continue
            neighbours.setdefault(
                route.source_landmark_id,
                [],
            ).append(
                (route.destination_landmark_id, route.movement_cost)
            )
            neighbours.setdefault(
                route.destination_landmark_id,
                [],
            ).append(
                (route.source_landmark_id, route.movement_cost)
            )

        queue: list[tuple[int, str, tuple[str, ...]]] = [
            (0, start_landmark_id, (start_landmark_id,))
        ]
        best_cost: dict[str, int] = {}

        while queue:
            cost, landmark_id, path = heapq.heappop(queue)
            if (
                landmark_id in best_cost
                and best_cost[landmark_id] <= cost
            ):
                continue

            best_cost[landmark_id] = cost
            if landmark_id == destination_landmark_id:
                return path

            for neighbour_id, route_cost in neighbours.get(
                landmark_id,
                (),
            ):
                next_cost = cost + route_cost
                if best_cost.get(
                    neighbour_id,
                    next_cost + 1,
                ) <= next_cost:
                    continue
                heapq.heappush(
                    queue,
                    (
                        next_cost,
                        neighbour_id,
                        (*path, neighbour_id),
                    ),
                )

        return None

    @classmethod
    def _movement_legs(
        cls,
        scene: CombatScene,
        combatant: CombatantState,
        destination_landmark_id: str,
    ) -> list[tuple[str, str, CombatRoute, int]]:
        def path_legs(
            path: tuple[str, ...],
        ) -> list[tuple[str, str, CombatRoute, int]]:
            result: list[tuple[str, str, CombatRoute, int]] = []
            for source_id, destination_id in zip(path, path[1:]):
                route = cls._route_between(
                    scene,
                    source_id,
                    destination_id,
                )
                if route is None:
                    raise CombatError(
                        "Combat route changed while movement was resolved."
                    )
                result.append(
                    (source_id, destination_id, route, 0)
                )
            return result

        if not combatant.is_between_landmarks:
            path = cls._shortest_path(
                scene,
                combatant.landmark_id,
                destination_landmark_id,
            )
            if path is None:
                raise CombatError(
                    f"No unblocked route reaches landmark "
                    f"'{destination_landmark_id}'."
                )
            return path_legs(path)

        source_id = combatant.route_source_landmark_id
        route_destination_id = combatant.route_destination_landmark_id
        assert source_id is not None
        assert route_destination_id is not None

        current_route = cls._route_between(
            scene,
            source_id,
            route_destination_id,
        )
        if current_route is None:
            raise CombatError(
                "The route under this combatant no longer exists."
            )

        candidates: list[
            tuple[int, list[tuple[str, str, CombatRoute, int]]]
        ] = []

        path_from_destination = cls._shortest_path(
            scene,
            route_destination_id,
            destination_landmark_id,
        )
        if path_from_destination is not None:
            candidates.append(
                (
                    combatant.route_cost
                    - combatant.route_progress
                    + cls._path_cost(
                        scene,
                        path_from_destination,
                    ),
                    [
                        (
                            source_id,
                            route_destination_id,
                            current_route,
                            combatant.route_progress,
                        ),
                        *path_legs(path_from_destination),
                    ],
                )
            )

        path_from_source = cls._shortest_path(
            scene,
            source_id,
            destination_landmark_id,
        )
        if path_from_source is not None:
            candidates.append(
                (
                    combatant.route_progress
                    + cls._path_cost(
                        scene,
                        path_from_source,
                    ),
                    [
                        (
                            route_destination_id,
                            source_id,
                            current_route,
                            combatant.route_cost
                            - combatant.route_progress,
                        ),
                        *path_legs(path_from_source),
                    ],
                )
            )

        if not candidates:
            raise CombatError(
                f"No unblocked route reaches landmark "
                f"'{destination_landmark_id}'."
            )

        candidates.sort(key=lambda candidate: candidate[0])
        return candidates[0][1]

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
        available = self._available_turn_combatants(scene)
        if not available:
            self.repository.set_all_combatants_acted(scene.id, False)
            scene = self._require_current(guild_id)
            available = self._available_turn_combatants(scene)
        if not available:
            self.repository.set_turn(
                scene.id,
                scene.round_number,
                None,
                None,
            )
            return self._require_current(guild_id)
        first = available[0]
        try:
            self.repository.reset_combatant_movement(
                scene.id,
                first.kind,
                first.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                first.kind,
                first.source_id,
            )
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
        return self._resolve_current_death_save(guild_id)

    def _resolve_current_death_save(
        self,
        guild_id: int,
    ) -> CombatScene:
        scene = self._require_current(guild_id)
        current = scene.current_combatant()
        if current is None or current.kind is not CombatantKind.CHARACTER:
            return scene

        character = self._character_by_source_id(current.source_id)
        assert character.character_id is not None
        state = self.database.get_character_combat_state(
            character.character_id
        )
        if state.status is not CharacterCombatStatus.DOWNED:
            return scene

        resolved, _ = self.roll_death_save(
            guild_id,
            current.source_id,
        )
        return resolved

    def roll_death_save(
        self,
        guild_id: int,
        character_source_id: str,
    ) -> tuple[CombatScene, DeathSaveResult]:
        scene = self._require_current(guild_id)
        current = scene.current_combatant()
        if (
            current is None
            or current.kind is not CombatantKind.CHARACTER
            or current.source_id != character_source_id
        ):
            raise CombatError(
                "Death saves can only be rolled for the current character."
            )

        character = self._character_by_source_id(character_source_id)
        assert character.character_id is not None
        state = self.database.get_character_combat_state(
            character.character_id
        )
        if state.status is not CharacterCombatStatus.DOWNED:
            raise CombatError(f"{character.name} is not downed.")
        if current.standard_action_spent:
            raise CombatError(
                f"{character.name}'s death save is already resolved this turn."
            )

        dc = 10 + math.ceil(abs(character.hp) / 2)
        vitality = self.database.get_character_attribute(
            character.character_id,
            "vitality",
        )
        modifier = (vitality - 10) // 2
        roll = random.randint(1, 20)
        total = roll + modifier
        success = roll == 20 or (
            roll != 1
            and total >= dc
        )
        updated_state = self.database.record_death_save(
            character.character_id,
            success=success,
        )

        result = DeathSaveResult(
            character_source_id=current.source_id,
            character_name=character.name,
            hp=character.hp,
            dc=dc,
            roll=roll,
            modifier=modifier,
            total=total,
            success=success,
            failed_death_saves=updated_state.failed_death_saves,
            status=updated_state.status.value,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                current.kind,
                current.source_id,
                True,
            )
            self.repository.set_movement_remaining(
                scene.id,
                current.kind,
                current.source_id,
                0,
            )
            if success:
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "death_save_success",
                    (
                        f"{character.name} rolled a death save: "
                        f"{roll}{modifier:+d} = {total} vs DC {dc}, success. "
                        f"{character.name} is stable."
                    ),
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_stabilized",
                    f"{character.name} stabilized at {character.hp} HP.",
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
            else:
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "death_save_failed",
                    (
                        f"{character.name} rolled a death save: "
                        f"{roll}{modifier:+d} = {total} vs DC {dc}, failed. "
                        f"Failed death saves: "
                        f"{updated_state.failed_death_saves}/3."
                    ),
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )

            if updated_state.status is CharacterCombatStatus.DEAD:
                self.repository.remove_combatant(
                    scene.id,
                    current.kind,
                    current.source_id,
                )
                self.repository.set_turn(
                    scene.id,
                    scene.round_number,
                    None,
                    None,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_died",
                    f"{character.name} died after three failed death saves.",
                    actor_kind=current.kind,
                    actor_source_id=current.source_id,
                    actor_name=current.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        if updated_state.status is CharacterCombatStatus.DEAD:
            return self._ensure_turn(guild_id), result
        return self._require_current(guild_id), result

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
            movement_budget = self._enemy_movement_budget(enemy.id)
            candidate = CombatantState(
                CombatantKind.ENEMY,
                enemy.id,
                enemy.name,
                destination_id,
                LandmarkRelation.AT,
                initiative_roll,
                initiative_score,
                movement_budget=movement_budget,
                movement_remaining=movement_budget,
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

                available = self._available_turn_combatants(
                    remaining_scene
                )
                next_round = scene.round_number
                if not available:
                    self.repository.set_all_combatants_acted(scene.id, False)
                    next_round += 1
                    remaining_scene = self._require_current(guild_id)
                    available = self._available_turn_combatants(
                        remaining_scene
                    )
                if not available:
                    self.repository.set_turn(
                        scene.id,
                        next_round,
                        None,
                        None,
                    )
                    return self._require_current(guild_id)

                next_combatant = available[0]
                self.repository.reset_combatant_movement(
                    scene.id,
                    next_combatant.kind,
                    next_combatant.source_id,
                )
                self.repository.reset_standard_action(
                    scene.id,
                    next_combatant.kind,
                    next_combatant.source_id,
                )
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
        ensured = self._ensure_turn(guild_id)
        if ensured.current_combatant() is None:
            return ensured
        return self._resolve_current_death_save(guild_id)

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
            available = self._available_turn_combatants(updated)
            next_round = scene.round_number
            if not available:
                self.repository.set_all_combatants_acted(scene.id, False)
                next_round += 1
                updated = self._require_current(guild_id)
                available = self._available_turn_combatants(updated)
            if not available:
                self.repository.set_turn(
                    scene.id,
                    next_round,
                    None,
                    None,
                )
                return self._require_current(guild_id)

            target = available[0]
            self.repository.reset_combatant_movement(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                target.kind,
                target.source_id,
            )
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
        return self._resolve_current_death_save(guild_id)

    def previous_turn(self, guild_id: int) -> CombatScene:
        scene = self._require_current(guild_id)
        if not scene.combatants:
            return scene
        if scene.current_combatant() is None:
            return self._ensure_turn(guild_id)

        ordered = scene.initiative_order()
        current_index = self._turn_index(scene)
        assert current_index is not None
        target = next(
            (
                ordered[(current_index - offset) % len(ordered)]
                for offset in range(1, len(ordered) + 1)
                if self._combatant_can_take_turn(
                    ordered[(current_index - offset) % len(ordered)]
                )
            ),
            None,
        )
        if target is None:
            return scene
        previous_index = ordered.index(target)
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
            self.repository.reset_combatant_movement(
                scene.id,
                target.kind,
                target.source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                target.kind,
                target.source_id,
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
            if not self._combatant_can_take_turn(target):
                raise CombatError(
                    f"{target.name} cannot take a turn in their current state."
                )
            self.repository.reset_combatant_movement(
                scene.id,
                parsed_kind,
                source_id,
            )
            self.repository.reset_standard_action(
                scene.id,
                parsed_kind,
                source_id,
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

    def attack_enemy(
        self,
        guild_id: int,
        target_enemy_id: str,
    ) -> tuple[CombatScene, AttackResult]:
        scene = self._require_current(guild_id)
        attacker = scene.current_combatant()
        if attacker is None:
            raise CombatError("There is no current combatant.")
        if attacker.kind is not CombatantKind.CHARACTER:
            raise CombatError(
                "Enemy attacks are not implemented in this combat slice yet."
            )
        if attacker.standard_action_spent:
            raise CombatError(
                f"{attacker.name} has already spent their Standard Action."
            )

        target = next(
            (
                combatant
                for combatant in scene.combatants
                if combatant.kind is CombatantKind.ENEMY
                and combatant.source_id == target_enemy_id
            ),
            None,
        )
        if target is None:
            raise CombatError(
                f"Enemy '{target_enemy_id}' is not in the active combat."
            )
        if not self._same_combat_position(attacker, target):
            raise CombatError(
                f"{target.name} is not within melee range of {attacker.name}."
            )

        enemy = self.world.get_enemy(target_enemy_id)
        if enemy is None:
            raise CombatError(
                "This legacy enemy has no combat stats. "
                "Use a structured enemy type for attacks."
            )
        if enemy.status is not EnemyStatus.ACTIVE or enemy.current_hp <= 0:
            raise CombatError(f"{enemy.name} is no longer an active target.")

        template = self.world.get_enemy_template(enemy.template_id)
        if template is None:
            raise CombatError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        character = self._character_by_source_id(attacker.source_id)
        assert character.character_id is not None
        character_id = character.character_id
        character_state = self.database.get_character_combat_state(
            character_id
        )
        if character_state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{attacker.name} cannot attack while "
                f"{character_state.status.value}."
            )

        weapon = self._equipped_attack_weapon(character_id)
        weapon_name = weapon.name if weapon is not None else "Unarmed"
        attack_attribute = self._weapon_attack_attribute(weapon)
        attribute_score = self.database.get_character_attribute(
            character_id,
            attack_attribute,
        )
        attack_modifier = (attribute_score - 10) // 2
        recovering = (
            character_state.status is CharacterCombatStatus.RECOVERING
        )
        attack_rolls, attack_roll = self._roll_d20(
            disadvantage=recovering,
        )
        attack_total = attack_roll + attack_modifier
        critical = attack_roll == 20
        hit = critical or (
            attack_roll != 1
            and attack_total >= template.defense_dc
        )

        damage_rolls: tuple[DamageRoll, ...] = ()
        raw_damage = 0
        reduction = 0
        reduction_type = "armor"
        final_damage = 0
        target_hp = enemy.current_hp
        target_defeated = False

        if hit:
            damage_parts = (
                weapon.damage_parts
                if weapon is not None and weapon.damage_parts
                else (DamagePart(4, "blunt"),)
            )
            damage_rolls = tuple(
                DamageRoll(
                    die=max(1, part.amount),
                    damage_type=part.damage_type,
                    roll=(
                        max(1, part.amount)
                        if critical
                        else random.randint(1, max(1, part.amount))
                    ),
                )
                for part in damage_parts
            )
            raw_damage = sum(part.roll for part in damage_rolls)
            magical_types = {
                "arcane",
                "cold",
                "fire",
                "lightning",
                "magic",
                "necrotic",
                "psychic",
                "radiant",
            }
            damage_types = {
                part.damage_type.casefold()
                for part in damage_rolls
            }
            if damage_types and damage_types <= magical_types:
                reduction_type = "magical_resistance"
                reduction = max(0, template.magical_resistance)
            else:
                reduction = max(0, template.armor)
            final_damage = max(1, raw_damage - reduction)
            target_hp = max(0, enemy.current_hp - final_damage)
            updated_enemy = self.world.update_enemy(
                enemy.id,
                name=enemy.name,
                description=enemy.description,
                current_hp=target_hp,
            )
            target_hp = updated_enemy.current_hp
            target_defeated = target_hp == 0

        result = AttackResult(
            attacker_kind=attacker.kind,
            attacker_source_id=attacker.source_id,
            attacker_name=attacker.name,
            target_kind=target.kind,
            target_source_id=target.source_id,
            target_name=target.name,
            weapon_name=weapon_name,
            attack_attribute=attack_attribute,
            attack_roll=attack_roll,
            attack_modifier=attack_modifier,
            attack_total=attack_total,
            defense_dc=template.defense_dc,
            hit=hit,
            critical=critical,
            damage_rolls=damage_rolls,
            raw_damage=raw_damage,
            reduction=reduction,
            reduction_type=reduction_type,
            final_damage=final_damage,
            target_hp=target_hp,
            target_max_hp=template.max_hp,
            target_defeated=target_defeated,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                attacker.kind,
                attacker.source_id,
                True,
            )

            if hit:
                critical_text = " critical" if critical else ""
                reduction_label = reduction_type.replace("_", " ")
                roll_text = (
                    f"{'/'.join(str(value) for value in attack_rolls)} "
                    f"-> {attack_roll}"
                    if recovering
                    else str(attack_roll)
                )
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{weapon_name}: {roll_text}"
                    f"{attack_modifier:+d} = {attack_total} vs "
                    f"Defense {template.defense_dc},"
                    f"{critical_text} hit for {final_damage} damage "
                    f"({raw_damage} raw, {reduction} "
                    f"{reduction_label} reduction). "
                    f"{target.name} has {target_hp}/{template.max_hp} HP."
                )
            else:
                roll_text = (
                    f"{'/'.join(str(value) for value in attack_rolls)} "
                    f"-> {attack_roll}"
                    if recovering
                    else str(attack_roll)
                )
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{weapon_name}: {roll_text}"
                    f"{attack_modifier:+d} = {attack_total} vs "
                    f"Defense {template.defense_dc}, miss."
                )

            self.repository.append_log(
                scene.id,
                scene.round_number,
                "attack_resolved",
                message,
                actor_kind=attacker.kind,
                actor_source_id=attacker.source_id,
                actor_name=attacker.name,
            )

            if target_defeated:
                self.repository.remove_combatant(
                    scene.id,
                    CombatantKind.ENEMY,
                    target.source_id,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_defeated",
                    f"{target.name} was defeated.",
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id), result

    def attack_character(
        self,
        guild_id: int,
        target_character_id: str,
    ) -> tuple[CombatScene, EnemyAttackResult]:
        scene = self._require_current(guild_id)
        attacker = scene.current_combatant()
        if attacker is None:
            raise CombatError("There is no current combatant.")
        if attacker.kind is not CombatantKind.ENEMY:
            raise CombatError(
                "Only an enemy can use this attack action."
            )
        if attacker.standard_action_spent:
            raise CombatError(
                f"{attacker.name} has already spent their Standard Action."
            )

        target = next(
            (
                combatant
                for combatant in scene.combatants
                if combatant.kind is CombatantKind.CHARACTER
                and combatant.source_id == target_character_id
            ),
            None,
        )
        if target is None:
            raise CombatError(
                f"Character '{target_character_id}' is not in the active combat."
            )
        if not self._same_combat_position(attacker, target):
            raise CombatError(
                f"{target.name} is not within melee range of {attacker.name}."
            )

        enemy = self.world.get_enemy(attacker.source_id)
        if enemy is None:
            raise CombatError(
                "This legacy enemy has no combat stats. "
                "Use a structured enemy type for attacks."
            )
        if enemy.status is not EnemyStatus.ACTIVE or enemy.current_hp <= 0:
            raise CombatError(f"{enemy.name} is no longer able to attack.")

        template = self.world.get_enemy_template(enemy.template_id)
        if template is None:
            raise CombatError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        character = self._character_by_source_id(target.source_id)
        assert character.character_id is not None
        character_id = character.character_id
        character_state = self.database.get_character_combat_state(
            character_id
        )
        if character_state.status not in {
            CharacterCombatStatus.ACTIVE,
            CharacterCombatStatus.RECOVERING,
        }:
            raise CombatError(
                f"{character.name} cannot defend while "
                f"{character_state.status.value}."
            )

        (
            defense_method,
            defense_attribute,
            defense_modifier,
        ) = self._automatic_defense(character_id)

        recovering = (
            character_state.status is CharacterCombatStatus.RECOVERING
        )
        defense_rolls, defense_roll = self._roll_d20(
            disadvantage=recovering,
        )
        defense_total = defense_roll + defense_modifier
        critical_defense = defense_roll == 20
        defended = critical_defense or (
            defense_roll != 1
            and defense_total >= template.attack_dc
        )

        damage_rolls: tuple[int, ...] = ()
        raw_damage = 0
        armor_reduction = 0
        final_damage = 0
        target_hp = character.hp

        if not defended:
            damage_rolls, raw_damage = self._roll_damage_expression(
                template.damage
            )
            armor_reduction, _ = self._equipped_armor_stats(character_id)
            if raw_damage > 0:
                final_damage = max(
                    1,
                    raw_damage - armor_reduction,
                )
                updated_character = self.database.damage_character_by_id(
                    character_id,
                    final_damage,
                )
                target_hp = updated_character.hp

        updated_character_state = self.database.get_character_combat_state(
            character_id
        )
        target_down = (
            updated_character_state.status is CharacterCombatStatus.DOWNED
        )
        target_dead = (
            updated_character_state.status is CharacterCombatStatus.DEAD
        )

        result = EnemyAttackResult(
            attacker_source_id=attacker.source_id,
            attacker_name=attacker.name,
            target_source_id=target.source_id,
            target_name=target.name,
            attack_profile=template.attack_profile,
            attack_dc=template.attack_dc,
            defense_method=defense_method,
            defense_attribute=defense_attribute,
            defense_roll=defense_roll,
            defense_modifier=defense_modifier,
            defense_total=defense_total,
            defended=defended,
            critical_defense=critical_defense,
            damage_expression=template.damage,
            damage_rolls=damage_rolls,
            raw_damage=raw_damage,
            armor_reduction=armor_reduction,
            final_damage=final_damage,
            target_hp=target_hp,
            target_max_hp=character.max_hp,
            target_down=target_down,
            target_status=updated_character_state.status.value,
            target_dead=target_dead,
        )

        try:
            self.repository.set_standard_action_spent(
                scene.id,
                attacker.kind,
                attacker.source_id,
                True,
            )

            defense_label = defense_method.replace("_", " ")
            defense_roll_text = (
                f"{'/'.join(str(value) for value in defense_rolls)} "
                f"-> {defense_roll}"
                if recovering
                else str(defense_roll)
            )
            if defended:
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{template.attack_profile}. "
                    f"{target.name} automatically used {defense_label}: "
                    f"{defense_roll_text}{defense_modifier:+d} = "
                    f"{defense_total} vs Attack DC {template.attack_dc}, "
                    f"defended."
                )
            else:
                message = (
                    f"{attacker.name} attacked {target.name} with "
                    f"{template.attack_profile}. "
                    f"{target.name} automatically used {defense_label}: "
                    f"{defense_roll_text}{defense_modifier:+d} = "
                    f"{defense_total} vs Attack DC {template.attack_dc}, "
                    f"failed. {final_damage} damage "
                    f"({raw_damage} raw, {armor_reduction} armor reduction). "
                    f"{target.name} has {target_hp}/{character.max_hp} HP."
                )

            self.repository.append_log(
                scene.id,
                scene.round_number,
                "enemy_attack_resolved",
                message,
                actor_kind=attacker.kind,
                actor_source_id=attacker.source_id,
                actor_name=attacker.name,
            )

            if target_down:
                death_save_dc = 10 + math.ceil(abs(target_hp) / 2)
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_downed",
                    (
                        f"{target.name} was downed at {target_hp} HP. "
                        f"Death Save DC is {death_save_dc}."
                    ),
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
            elif target_dead:
                self.repository.remove_combatant(
                    scene.id,
                    target.kind,
                    target.source_id,
                )
                self.repository.append_log(
                    scene.id,
                    scene.round_number,
                    "combatant_died",
                    (
                        f"{target.name} reached {target_hp} HP "
                        f"(-{character.max_hp} Max HP) and died instantly."
                    ),
                    actor_kind=target.kind,
                    actor_source_id=target.source_id,
                    actor_name=target.name,
                )
        except ValueError as error:
            raise CombatError(str(error)) from error

        return self._require_current(guild_id), result

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

            legs = self._movement_legs(
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

    def _require_current(self, guild_id: int) -> CombatScene:
        scene = self.current(guild_id)
        if scene is None:
            raise CombatError("There is no active combat scene.")
        return scene
