"""Combat scene lifecycle orchestration."""

from __future__ import annotations

from dataclasses import replace

from .errors import CombatError
from .layout import cardinal_direction, door_position, next_open_position
from .models import (
    CombatLandmark,
    CombatScene,
    CombatantKind,
    CombatantState,
    CoverLevel,
    LandmarkDistance,
    LandmarkRelation,
)
from ..characters.models import CharacterCombatStatus
from ..world.dungeon import ConnectionType
from ..world.enemies import EnemyStatus


ROOM_CORNER_SPECS = (
    ("room:corner:nw", "Northwest Corner", 0.12, 0.18),
    ("room:corner:ne", "Northeast Corner", 0.80, 0.18),
    ("room:corner:sw", "Southwest Corner", 0.12, 0.82),
    ("room:corner:se", "Southeast Corner", 0.80, 0.82),
)


class CombatLifecycleMixin:
    """Start, access, and end combat scenes."""

    @staticmethod
    def _combat_hunger_damage_bonus(
        damage_taken: int,
        max_hp: int,
    ) -> int:
        if damage_taken <= 0 or max_hp <= 0:
            return 0
        damage_percent = (damage_taken / max_hp) * 100
        if damage_percent <= 25:
            return 0
        if damage_percent <= 50:
            return 2
        if damage_percent <= 75:
            return 4
        return 6

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
                id=landmark_id,
                name=name,
                description="A tactical position near the corner of the room.",
                feature_type="corner",
                synthetic=True,
                x=x,
                y=y,
            )
            for landmark_id, name, x, y in ROOM_CORNER_SPECS
        )
        landmarks.extend(
            CombatLandmark(
                id=f"feature:{feature.id}",
                name=feature.name,
                description=feature.description,
                source_feature_id=feature.id,
                feature_type=feature.feature_type.value,
                cover=CoverLevel.HALF,
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
                    cardinal_direction(exit_name),
                )
            )

        direction_counts: dict[str, int] = {}
        for _, _, _, direction in door_specs:
            if direction is not None:
                direction_counts[direction] = direction_counts.get(direction, 0) + 1
        direction_indices: dict[str, int] = {}
        for connection, exit_name, adjacent_room_id, direction in door_specs:
            adjacent_room = self.world.get_room(adjacent_room_id)
            connection_key = connection.connection_id or f"{room_id}:{len(landmarks)}"
            landmark_id = f"door:{connection_key}"
            x = None
            y = None
            if direction is not None:
                index = direction_indices.get(direction, 0)
                direction_indices[direction] = index + 1
                x, y = door_position(
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

        occupied_landmarks = [
            landmark
            for landmark in landmarks
            if landmark.x is not None and landmark.y is not None
        ]
        positioned_landmarks: list[CombatLandmark] = []
        for landmark in landmarks:
            if landmark.x is None or landmark.y is None:
                x, y = next_open_position(occupied_landmarks)
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
            for landmark in landmarks:
                if landmark.id == self.CENTER_LANDMARK_ID:
                    continue
                self.repository.set_route(
                    scene.id,
                    self.CENTER_LANDMARK_ID,
                    landmark.id,
                    LandmarkDistance.NEAR,
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

    def current(self, guild_id: int) -> CombatScene | None:
        return self.repository.get_active_scene(guild_id)

    def end(self, guild_id: int) -> CombatScene:
        current = self._require_current(guild_id)

        for combatant in current.combatants:
            if combatant.kind is not CombatantKind.CHARACTER:
                continue
            try:
                character_id = int(combatant.source_id)
            except ValueError:
                continue
            character = self.database.get_character_by_global_id(character_id)
            if character is None:
                continue
            state = self.database.get_character_combat_state(character_id)
            if state.status is CharacterCombatStatus.DEAD:
                continue

            base_hunger = 5
            exertion_hunger = 2 if combatant.heavy_exertion else 0
            damage_hunger = self._combat_hunger_damage_bonus(
                combatant.damage_taken,
                character.max_hp,
            )
            hunger_gain = base_hunger + exertion_hunger + damage_hunger
            updated = self.database.adjust_character_hunger(
                character_id,
                hunger_gain,
            )
            hunger_parts = ["5 combat"]
            if exertion_hunger:
                hunger_parts.append("2 exertion")
            if damage_hunger:
                hunger_parts.append(f"{damage_hunger} damage")
            self.repository.append_log(
                current.id,
                current.round_number,
                "hunger_changed",
                (
                    f"{combatant.name} gained {hunger_gain} Hunger "
                    f"({' + '.join(hunger_parts)}). "
                    f"Hunger is now {updated.hunger}/100."
                ),
                actor_kind=combatant.kind,
                actor_source_id=combatant.source_id,
                actor_name=combatant.name,
            )

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
