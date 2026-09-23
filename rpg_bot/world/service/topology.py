"""Area, room, connection, floor, and dungeon topology operations."""

from __future__ import annotations

from ..dungeon import (
    ConnectionType,
    Dungeon,
    Floor,
    RoomConnection,
    TrapDamageType,
    TrapState,
)
from ..models import Area, AreaGraph, Room


class WorldTopologyMixin:
    def create_area(
        self, area_id: str, name: str, description: str | None = None
    ) -> Area:
        return self.database.create_area(area_id, name, description)

    def create_room(
        self,
        room_id: str,
        area_id: str,
        name: str,
        description: str | None = None,
        *,
        editor_x: float | None = None,
        editor_y: float | None = None,
        floor_id: str | None = None,
        width: float = 1.0,
        height: float = 1.0,
        scene_image_path: str | None = None,
        scene_image_url: str | None = None,
        scene_prompt: str | None = None,
    ) -> Room:
        room = self.database.create_room(
            room_id,
            area_id,
            name,
            description,
            floor_id=floor_id,
            width=width,
            height=height,
            scene_image_path=scene_image_path,
            scene_image_url=scene_image_url,
            scene_prompt=scene_prompt,
        )
        if editor_x is not None or editor_y is not None:
            if editor_x is None or editor_y is None:
                self.database.delete_room(room.id)
                raise ValueError("Both editor coordinates are required together.")
            self.database.set_room_editor_position(room.id, editor_x, editor_y)
        return room

    def list_areas(self) -> tuple[Area, ...]:
        return self.database.list_areas()

    def area_graph(self, area_id: str) -> AreaGraph:
        return self.database.get_area_graph(area_id)

    def update_room(
        self, room_id: str, name: str, description: str | None = None
    ) -> Room:
        return self.database.update_room(room_id, name, description)

    def set_room_scene_image(
        self, room_id: str, scene_image_path: str | None
    ) -> Room:
        return self.database.set_room_scene_image(room_id, scene_image_path)

    def delete_room(self, room_id: str) -> None:
        self.database.delete_room(room_id)

    def set_room_editor_position(self, room_id: str, x: float, y: float) -> None:
        self.database.set_room_editor_position(room_id, x, y)

    def connect_rooms(
        self,
        room_id: str,
        exit_name: str,
        destination_room_id: str,
        *,
        return_exit_name: str | None = None,
        connection_type: ConnectionType = ConnectionType.PASSAGE,
        hidden: bool = False,
        has_lock: bool = False,
        is_locked: bool = False,
        unlock_difficulty: int | None = None,
        is_broken: bool = False,
        is_open: bool = False,
        has_trap: bool = False,
        trap_state: TrapState | None = None,
        trap_detection_difficulty: int | None = None,
        trap_disarm_difficulty: int | None = None,
        trap_damage_type: TrapDamageType | None = None,
        trap_damage: int | None = None,
    ) -> RoomConnection:
        return self.database.connect_rooms(
            room_id,
            exit_name,
            destination_room_id,
            return_exit_name=return_exit_name,
            connection_type=connection_type,
            hidden=hidden,
            has_lock=has_lock,
            is_locked=is_locked,
            unlock_difficulty=unlock_difficulty,
            is_broken=is_broken,
            is_open=is_open,
            has_trap=has_trap,
            trap_state=trap_state,
            trap_detection_difficulty=trap_detection_difficulty,
            trap_disarm_difficulty=trap_disarm_difficulty,
            trap_damage_type=trap_damage_type,
            trap_damage=trap_damage,
        )

    def set_connection_direction(
        self,
        room_id: str,
        exit_name: str,
        *,
        bidirectional: bool,
        return_exit_name: str | None = None,
    ) -> None:
        self.database.set_connection_direction(
            room_id,
            exit_name,
            bidirectional=bidirectional,
            return_exit_name=return_exit_name,
        )

    def set_connection_type(
        self,
        room_id: str,
        exit_name: str,
        connection_type: ConnectionType,
    ) -> None:
        self.database.set_connection_type(room_id, exit_name, connection_type)

    def set_connection_lock(
        self,
        room_id: str,
        exit_name: str,
        *,
        has_lock: bool,
        is_locked: bool,
        is_broken: bool = False,
        unlock_difficulty: int | None = None,
    ) -> None:
        self.database.set_connection_lock(
            room_id,
            exit_name,
            has_lock=has_lock,
            is_locked=is_locked,
            is_broken=is_broken,
            unlock_difficulty=unlock_difficulty,
        )

    def set_connection_open(
        self,
        room_id: str,
        exit_name: str,
        *,
        is_open: bool,
    ) -> None:
        self.database.set_connection_open(
            room_id,
            exit_name,
            is_open=is_open,
        )

    def set_connection_trap_disarm_difficulty(
        self,
        room_id: str,
        exit_name: str,
        difficulty: int | None,
    ) -> None:
        self.database.set_connection_trap_disarm_difficulty(
            room_id, exit_name, difficulty
        )

    def set_connection_trap_state(
        self,
        connection_id: str,
        state: TrapState,
    ) -> None:
        self.database.set_connection_trap_state(connection_id, state)

    def disconnect_connection(self, room_id: str, exit_name: str) -> None:
        self.database.disconnect_connection(room_id, exit_name)

    def set_connection_trap(
        self,
        room_id: str,
        exit_name: str,
        *,
        has_trap: bool,
        trap_state: TrapState | None = None,
        trap_detection_difficulty: int | None = None,
        trap_damage_type: TrapDamageType | None = None,
        trap_damage: int | None = None,
    ) -> None:
        self.database.set_connection_trap(
            room_id,
            exit_name,
            has_trap=has_trap,
            trap_state=trap_state,
            trap_detection_difficulty=trap_detection_difficulty,
            trap_damage_type=trap_damage_type,
            trap_damage=trap_damage,
        )

    def create_floor(
        self, floor_id: str, dungeon_id: str, floor_number: int, name: str
    ) -> Floor:
        return self.database.create_floor(floor_id, dungeon_id, floor_number, name)

    def list_floors(self, dungeon_id: str) -> tuple[Floor, ...]:
        return self.database.list_floors(dungeon_id)

    def get_dungeon(self, dungeon_id: str) -> Dungeon | None:
        return self.database.get_dungeon(dungeon_id)

    def list_dungeons(self) -> tuple[Dungeon, ...]:
        return self.database.list_dungeons()

    def disconnect_rooms(self, room_id: str, exit_name: str) -> None:
        self.database.disconnect_rooms(room_id, exit_name)

    def get_room(self, room_id: str) -> Room | None:
        return self.database.get_room(room_id)
