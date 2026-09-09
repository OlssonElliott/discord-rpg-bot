"""Framework-neutral JSON API for the local DM dashboard."""

from dataclasses import asdict
import re
from typing import Any

from .world import AreaGraph, EntityKind, InventoryHolder, RoomEditorNode, WorldError
from .world_service import WorldService


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def _stack_data(stack: object) -> JsonObject:
    return {
        "id": stack.item.id,
        "name": stack.item.name,
        "description": stack.item.description,
        "quantity": stack.quantity,
    }


def _node_data(node: RoomEditorNode) -> JsonObject:
    room = node.room
    return {
        "id": room.id,
        "area_id": room.area_id,
        "name": room.name,
        "description": room.description or "",
        "position": {"x": node.x, "y": node.y},
        "counts": {
            "players": len(room.characters),
            "enemies": len(room.enemies),
            "items": sum(stack.quantity for stack in room.loose_items),
            "containers": len(room.containers),
        },
        "players": [
            {"id": character.character_id, "name": character.name}
            for character in room.characters
        ],
        "enemies": [asdict(entity) for entity in room.enemies],
        "npcs": [asdict(entity) for entity in room.npcs],
        "containers": [asdict(entity) for entity in room.containers],
        "loose_items": [_stack_data(stack) for stack in room.loose_items],
    }


def _graph_data(graph: AreaGraph) -> JsonObject:
    return {
        "area": {
            "id": graph.area.id,
            "name": graph.area.name,
            "description": graph.area.description or "",
        },
        "nodes": [_node_data(node) for node in graph.nodes],
        "connections": [asdict(connection) for connection in graph.connections],
    }


def _character_data(character: object) -> JsonObject:
    return {
        "id": character.character_id,
        "discord_user_id": character.discord_user_id,
        "name": character.name,
        "current_room_id": character.current_room_id,
        "is_active": character.is_active,
    }


class DashboardAPI:
    """Translate HTTP-shaped requests into deterministic service calls."""

    def __init__(self, world: WorldService) -> None:
        self.world = world

    def handle(
        self,
        method: str,
        path: str,
        body: JsonObject | None = None,
    ) -> ApiResponse:
        body = body or {}
        try:
            return self._handle(method.upper(), path.rstrip("/") or "/", body)
        except (ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def _handle(self, method: str, path: str, body: JsonObject) -> ApiResponse:
        if method == "GET" and path == "/api/characters":
            return 200, [
                _character_data(character) for character in self.world.list_characters()
            ]

        match = re.fullmatch(r"/api/characters/(\d+)/room", path)
        if method == "PATCH" and match:
            character_id = int(match.group(1))
            room = self.world.place_character(
                character_id, self._text(body, "room_id")
            )
            return 200, {"id": character_id, "current_room_id": room.id}

        if method == "GET" and path == "/api/areas":
            return 200, [
                {
                    "id": area.id,
                    "name": area.name,
                    "description": area.description or "",
                    "room_count": len(area.room_ids),
                }
                for area in self.world.list_areas()
            ]

        if method == "POST" and path == "/api/areas":
            area = self.world.create_area(
                self._text(body, "id"),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 201, {"id": area.id, "name": area.name, "description": area.description or ""}

        match = re.fullmatch(r"/api/areas/([^/]+)/graph", path)
        if method == "GET" and match:
            return 200, _graph_data(self.world.area_graph(match.group(1)))

        match = re.fullmatch(r"/api/areas/([^/]+)/rooms", path)
        if method == "POST" and match:
            room = self.world.create_room(
                self._text(body, "id"),
                match.group(1),
                self._text(body, "name"),
                self._optional_text(body, "description"),
                editor_x=self._number(body, "x"),
                editor_y=self._number(body, "y"),
            )
            return 201, {"id": room.id}

        match = re.fullmatch(r"/api/rooms/([^/]+)", path)
        if match and method == "PATCH":
            room = self.world.update_room(
                match.group(1),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 200, {"id": room.id, "name": room.name, "description": room.description or ""}
        if match and method == "DELETE":
            self.world.delete_room(match.group(1))
            return 200, {"deleted": match.group(1)}

        match = re.fullmatch(r"/api/rooms/([^/]+)/position", path)
        if match and method == "PATCH":
            self.world.set_room_editor_position(
                match.group(1), self._number(body, "x"), self._number(body, "y")
            )
            return 200, {"id": match.group(1), "position": {"x": body["x"], "y": body["y"]}}

        match = re.fullmatch(r"/api/rooms/([^/]+)/entities", path)
        if match and method == "POST":
            try:
                kind = EntityKind(self._text(body, "kind"))
            except ValueError as error:
                raise ValueError("Entity kind must be enemy, npc, or container.") from error
            entity = self.world.create_entity(
                self._text(body, "id"),
                match.group(1),
                kind,
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 201, asdict(entity)

        match = re.fullmatch(r"/api/rooms/([^/]+)/items", path)
        if match and method == "POST":
            room_id = match.group(1)
            if self.world.get_room(room_id) is None:
                raise ValueError(f"Room '{room_id}' does not exist.")
            quantity = self._integer(body, "quantity", default=1)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            item = self.world.create_item(
                self._text(body, "id"),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            stack = self.world.place_item(
                InventoryHolder.room(room_id),
                item.id,
                quantity,
            )
            return 201, _stack_data(stack)

        if path == "/api/connections" and method == "POST":
            self.world.connect_rooms(
                self._text(body, "source_room_id"),
                self._text(body, "exit_name"),
                self._text(body, "destination_room_id"),
            )
            return 201, {
                "source_room_id": body["source_room_id"],
                "exit_name": body["exit_name"],
                "destination_room_id": body["destination_room_id"],
            }
        if path == "/api/connections" and method == "DELETE":
            self.world.disconnect_rooms(
                self._text(body, "source_room_id"), self._text(body, "exit_name")
            )
            return 200, {"deleted": True}

        return 404, {"error": "Not found."}

    @staticmethod
    def _text(body: JsonObject, field: str) -> str:
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' is required.")
        return value.strip()

    @staticmethod
    def _optional_text(body: JsonObject, field: str) -> str | None:
        value = body.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"'{field}' must be text.")
        return value.strip() or None

    @staticmethod
    def _number(body: JsonObject, field: str) -> float:
        value = body.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{field}' must be a number.")
        return float(value)

    @staticmethod
    def _integer(body: JsonObject, field: str, *, default: int) -> int:
        value = body.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{field}' must be an integer.")
        return value
