"""Room and dungeon-editor persistence for the database facade."""

from __future__ import annotations

import math
import sqlite3

from ...world.dungeon import ConnectionType, TrapDamageType, TrapState
from ...world import (
    AreaGraph,
    Exit,
    GraphConnection,
    Item,
    ItemStack,
    NotFoundError,
    Room,
    RoomEditorNode,
)


class DatabaseRoomsMixin:
    """Persist room identity, editor layout, graph views, and scene images."""

    def create_room(
        self,
        room_id: str,
        area_id: str,
        name: str,
        description: str | None = None,
        *,
        floor_id: str | None = None,
        width: float = 1.0,
        height: float = 1.0,
        scene_image_path: str | None = None,
        scene_image_url: str | None = None,
        scene_prompt: str | None = None,
    ) -> Room:
        room_id = self._clean_identifier(room_id, "Room ID")
        name = self._clean_name(name, "Room name")
        with self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM areas WHERE id = ?", (area_id,)
            ).fetchone():
                raise NotFoundError(f"Area '{area_id}' does not exist.")
            floor_id = floor_id or f"{area_id}:floor:1"
            floor = connection.execute(
                "SELECT dungeon_id FROM dungeon_floors WHERE id = ?", (floor_id,)
            ).fetchone()
            if floor is None or floor["dungeon_id"] != area_id:
                raise NotFoundError(
                    f"Floor '{floor_id}' does not exist in dungeon '{area_id}'."
                )
            width = self._validate_room_dimension(width, "width")
            height = self._validate_room_dimension(height, "height")
            try:
                connection.execute(
                    """
                    INSERT INTO rooms (
                        id, area_id, name, description, floor_id, width, height,
                        scene_image_path, scene_image_url, scene_prompt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        room_id, area_id, name, description, floor_id, width, height,
                        scene_image_path, scene_image_url, scene_prompt,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Room '{room_id}' already exists.") from error
        room = self.get_room(room_id)
        assert room is not None
        return room

    def update_room(
        self, room_id: str, name: str, description: str | None = None
    ) -> Room:
        name = self._clean_name(name, "Room name")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE rooms SET name = ?, description = ? WHERE id = ?",
                (name, description, room_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Room '{room_id}' does not exist.")
        room = self.get_room(room_id)
        assert room is not None
        return room

    def delete_room(self, room_id: str) -> None:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            occupied = connection.execute(
                "SELECT 1 FROM characters WHERE current_room_id = ? LIMIT 1", (room_id,)
            ).fetchone()
            entities = connection.execute(
                "SELECT 1 FROM world_entities WHERE room_id = ? LIMIT 1", (room_id,)
            ).fetchone()
            items = connection.execute(
                """
                SELECT 1 FROM inventory_stacks
                WHERE holder_kind = 'room' AND holder_id = ? LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if occupied or entities or items:
                raise ValueError(
                    "Move characters, entities, and loose items before deleting this room."
                )
            connection.execute(
                "DELETE FROM room_exits WHERE room_id = ? OR destination_room_id = ?",
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM character_room_knowledge WHERE room_id = ?", (room_id,)
            )
            connection.execute(
                "UPDATE player_view_states SET focused_room_id = NULL WHERE focused_room_id = ?",
                (room_id,),
            )
            connection.execute(
                """
                DELETE FROM character_known_connections
                WHERE connection_id IN (
                    SELECT id FROM room_connections
                    WHERE from_room_id = ? OR to_room_id = ?
                )
                """,
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM room_connections WHERE from_room_id = ? OR to_room_id = ?",
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM room_editor_metadata WHERE room_id = ?", (room_id,)
            )
            connection.execute("DELETE FROM rooms WHERE id = ?", (room_id,))

    def set_room_editor_position(self, room_id: str, x: float, y: float) -> None:
        x = self._validate_editor_coordinate(x, "x")
        y = self._validate_editor_coordinate(y, "y")
        with self._connect() as connection:
            self._require_room(connection, room_id)
            connection.execute(
                """
                INSERT INTO room_editor_metadata (room_id, x, y) VALUES (?, ?, ?)
                ON CONFLICT(room_id) DO UPDATE SET x = excluded.x, y = excluded.y
                """,
                (room_id, x, y),
            )

    def get_area_graph(self, area_id: str) -> AreaGraph:
        area = self.get_area(area_id)
        if area is None:
            raise NotFoundError(f"Area '{area_id}' does not exist.")
        with self._connect() as connection:
            nodes = []
            connections = []
            for index, room_id in enumerate(area.room_ids):
                room_row = self._require_room(connection, room_id)
                room = self._to_room(connection, room_row)
                position = connection.execute(
                    "SELECT x, y FROM room_editor_metadata WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
                x = position["x"] if position else 120.0 + (index % 3) * 300.0
                y = position["y"] if position else 100.0 + (index // 3) * 220.0
                nodes.append(RoomEditorNode(room, x, y))
            connection_rows = connection.execute(
                """
                SELECT links.id, links.from_room_id, links.exit_name,
                       links.to_room_id, links.return_exit_name,
                       links.bidirectional, links.hidden, links.connection_type,
                       links.has_lock, links.is_locked, links.unlock_difficulty,
                       links.is_broken, links.is_open,
                       links.has_trap, links.trap_state,
                       links.trap_detection_difficulty, links.trap_disarm_difficulty,
                       links.trap_damage_type, links.trap_damage
                FROM room_connections AS links
                JOIN rooms AS source ON source.id = links.from_room_id
                WHERE source.area_id = ?
                ORDER BY source.name COLLATE NOCASE, links.exit_name COLLATE NOCASE
                """,
                (area_id,),
            ).fetchall()
            connections = [
                GraphConnection(
                    row["from_room_id"],
                    row["exit_name"],
                    row["to_room_id"],
                    row["id"],
                    row["return_exit_name"],
                    bool(row["bidirectional"]),
                    bool(row["hidden"]),
                    ConnectionType(row["connection_type"]),
                    bool(row["has_lock"]),
                    bool(row["is_locked"]),
                    row["unlock_difficulty"],
                    bool(row["is_broken"]),
                    bool(row["is_open"]),
                    bool(row["has_trap"]),
                    (
                        TrapState(row["trap_state"])
                        if row["trap_state"] is not None
                        else None
                    ),
                    row["trap_detection_difficulty"],
                    row["trap_disarm_difficulty"],
                    (
                        TrapDamageType(row["trap_damage_type"])
                        if row["trap_damage_type"] is not None
                        else None
                    ),
                    row["trap_damage"],
                )
                for row in connection_rows
            ]
        return AreaGraph(area, tuple(nodes), tuple(connections))

    def get_room(self, room_id: str) -> Room | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, area_id, name, description, floor_id, width, height,
                       scene_image_path, scene_image_url, scene_prompt
                FROM rooms WHERE id = ?
                """,
                (room_id,),
            ).fetchone()
            return self._to_room(connection, row) if row else None

    def set_room_scene_image(
        self, room_id: str, scene_image_path: str | None
    ) -> Room:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            connection.execute(
                """
                UPDATE rooms
                SET scene_image_path = ?, scene_image_url = NULL
                WHERE id = ?
                """,
                (scene_image_path, room_id),
            )
            self._queue_map_refresh_for_room(
                connection, room_id, include_focused=True
            )
        room = self.get_room(room_id)
        assert room is not None
        return room

    @staticmethod
    def _validate_editor_coordinate(value: float, axis: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Editor {axis} coordinate must be a number.")
        coordinate = float(value)
        if not math.isfinite(coordinate) or abs(coordinate) > 1_000_000:
            raise ValueError(f"Editor {axis} coordinate is outside the valid range.")
        return coordinate

    @staticmethod
    def _validate_room_dimension(value: float, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Room {label} must be a number.")
        dimension = float(value)
        if not math.isfinite(dimension) or dimension <= 0 or dimension > 1_000_000:
            raise ValueError(f"Room {label} must be a positive finite number.")
        return dimension

    @classmethod
    def _to_room(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> Room:
        position = connection.execute(
            "SELECT x, y FROM room_editor_metadata WHERE room_id = ?", (row["id"],)
        ).fetchone()
        exits = tuple(
            Exit(exit_row["name"], exit_row["destination_room_id"])
            for exit_row in connection.execute(
                """
                SELECT name, destination_room_id FROM room_exits
                WHERE room_id = ? ORDER BY name COLLATE NOCASE
                """,
                (row["id"],),
            )
        )
        entities = tuple(
            cls._to_entity(entity_row)
            for entity_row in connection.execute(
                """
                SELECT id, room_id, kind, name, description FROM world_entities
                WHERE room_id = ? ORDER BY name COLLATE NOCASE, id
                """,
                (row["id"],),
            )
        )
        character_rows = connection.execute(
            """
            SELECT id, discord_user_id, name, hp, max_hp, stance,
                   lineage, race, age, gender,
                   strength, dexterity, arcana, vitality, insight, personality,
                   is_active, is_archived, portrait_key, current_room_id
            FROM characters
            WHERE current_room_id = ? AND is_archived = 0
            ORDER BY name COLLATE NOCASE, id
            """,
            (row["id"],),
        ).fetchall()
        characters = tuple(
            cls._to_character_with_skills(connection, character_row)
            for character_row in character_rows
        )
        loose_items = tuple(
            ItemStack(
                Item(
                    item_row["id"],
                    item_row["name"],
                    item_row["description"],
                    bool(item_row["stackable"]),
                ),
                item_row["quantity"],
            )
            for item_row in connection.execute(
                """
                SELECT i.id, i.name, i.description, i.stackable, s.quantity
                FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
                WHERE s.holder_kind = 'room' AND s.holder_id = ?
                ORDER BY i.name COLLATE NOCASE, i.id
                """,
                (row["id"],),
            )
        )
        return Room(
            row["id"], row["area_id"], row["name"], row["description"],
            exits, entities, characters, loose_items,
            row["floor_id"],
            position["x"] if position else 0.0,
            position["y"] if position else 0.0,
            row["width"],
            row["height"],
            row["scene_image_path"],
            row["scene_image_url"],
            row["scene_prompt"],
        )
