"""Framework-neutral JSON API for the local DM dashboard."""

from dataclasses import asdict
import re
from typing import Any

from .inventory import ItemTemplate, ItemType, WeaponGrip
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


def _template_data(template: ItemTemplate) -> JsonObject:
    data: JsonObject = {
        "id": template.template_id,
        "item_type": template.item_type.value,
        "name": template.name,
        "rarity": template.rarity,
        "value": template.value,
        "description": template.description,
        "weight": template.weight,
        "slot_cost": template.slot_cost,
        "stackable": template.stackable,
        "content": template.content,
    }
    if template.item_type is ItemType.WEAPON:
        data.update(
            grip=template.grip.value if template.grip else "one_handed",
            durability=template.durability,
            damage=template.damage_parts[0].amount if template.damage_parts else 1,
            damage_type=(
                template.damage_parts[0].damage_type
                if template.damage_parts
                else "physical"
            ),
        )
    elif template.item_type is ItemType.ARMOR:
        data.update(
            protection=template.protection,
            dodge_penalty=template.dodge_penalty,
            strength_requirement=template.strength_requirement,
        )
    elif template.item_type is ItemType.CONTAINER:
        data.update(capacity=template.capacity, can_equip=template.can_equip)
    elif template.item_type is ItemType.CONSUMABLE:
        data["affected_amount"] = template.affected_amount
    return data


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

        if method == "GET" and path == "/api/items":
            return 200, [
                _template_data(template)
                for template in sorted(
                    self.world.list_item_templates(),
                    key=lambda template: (template.name.casefold(), template.template_id),
                )
            ]

        if method == "POST" and path == "/api/items":
            record = self._item_record(body)
            template = self.world.create_item_template(record)
            return 201, _template_data(template)

        match = re.fullmatch(r"/api/items/([^/]+)", path)
        if method == "PUT" and match:
            record = self._item_record({**body, "id": match.group(1)})
            template = self.world.update_item_template(match.group(1), record)
            return 200, _template_data(template)

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
            stack = self.world.place_catalog_item(
                InventoryHolder.room(room_id),
                self._text(body, "item_id"),
                quantity,
            )
            return 201, _stack_data(stack)

        if path == "/api/connections" and method == "POST":
            exit_name = self._text(body, "exit_name")
            bidirectional = self._boolean(body, "bidirectional", default=True)
            return_exit_name = (
                self._optional_text(body, "return_exit_name") or exit_name
                if bidirectional
                else None
            )
            self.world.connect_rooms(
                self._text(body, "source_room_id"),
                exit_name,
                self._text(body, "destination_room_id"),
                return_exit_name=return_exit_name,
            )
            return 201, {
                "source_room_id": body["source_room_id"],
                "exit_name": exit_name,
                "destination_room_id": body["destination_room_id"],
                "return_exit_name": return_exit_name,
                "bidirectional": bidirectional,
            }
        if path == "/api/connections" and method == "PATCH":
            source_room_id = self._text(body, "source_room_id")
            exit_name = self._text(body, "exit_name")
            bidirectional = self._boolean(body, "bidirectional", default=True)
            return_exit_name = (
                self._optional_text(body, "return_exit_name") or exit_name
                if bidirectional
                else None
            )
            self.world.set_connection_direction(
                source_room_id,
                exit_name,
                bidirectional=bidirectional,
                return_exit_name=return_exit_name,
            )
            return 200, {
                "source_room_id": source_room_id,
                "exit_name": exit_name,
                "bidirectional": bidirectional,
                "return_exit_name": return_exit_name,
            }
        if path == "/api/connections" and method == "DELETE":
            self.world.disconnect_connection(
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

    @classmethod
    def _item_record(cls, body: JsonObject) -> dict[str, object]:
        try:
            item_type = ItemType(cls._text(body, "item_type"))
        except ValueError as error:
            raise ValueError(
                "Item type must be weapon, armor, clothing, container, consumable, readable, or misc."
            ) from error

        value = cls._integer(body, "value", default=0)
        weight = cls._integer(body, "weight", default=0)
        default_slot_cost = 0 if item_type is ItemType.READABLE and weight == 0 else 1
        slot_cost = cls._integer(body, "slot_cost", default=default_slot_cost)
        if value < 0 or weight < 0 or slot_cost < 0:
            raise ValueError("Item value, weight, and slot cost cannot be negative.")
        record: dict[str, object] = {
            "item_type": item_type.value,
            "id": cls._text(body, "id"),
            "name": cls._text(body, "name"),
            "rarity": cls._text_or_default(body, "rarity", "Common"),
            "value": value,
            "description": cls._optional_text(body, "description") or "",
            "weight": weight,
            "slot_cost": slot_cost,
            "tags": [],
            "modifiers": [],
            "requirements": [],
        }
        if item_type is ItemType.WEAPON:
            try:
                grip = WeaponGrip(cls._text_or_default(body, "grip", "one_handed"))
            except ValueError as error:
                raise ValueError("Weapon grip must be one_handed or two_handed.") from error
            durability = cls._positive_integer(body, "durability", default=40)
            damage = cls._positive_integer(body, "damage", default=1)
            record.update(
                grip=grip.value,
                durability=durability,
                damage_parts=[
                    {
                        "amount": damage,
                        "damage_type": cls._text_or_default(
                            body, "damage_type", "physical"
                        ),
                    }
                ],
            )
        elif item_type is ItemType.ARMOR:
            protection = cls._positive_integer(body, "protection", default=1)
            strength_requirement = cls._integer(
                body, "strength_requirement", default=0
            )
            if strength_requirement < 0:
                raise ValueError("Strength requirement cannot be negative.")
            record.update(
                protection_current=protection,
                protection_max=protection,
                dodge_penalty=cls._integer(body, "dodge_penalty", default=0),
                strength_requirement=strength_requirement or None,
            )
        elif item_type is ItemType.CONTAINER:
            record.update(
                capacity=cls._positive_integer(body, "capacity", default=10),
                items=[],
                can_equip=cls._boolean(body, "can_equip", default=False),
                locked=False,
            )
        elif item_type is ItemType.CONSUMABLE:
            record.update(
                affected_stat="hp",
                affected_amount=cls._positive_integer(
                    body, "affected_amount", default=1
                ),
                side_effects=None,
            )
        elif item_type is ItemType.READABLE:
            content = body.get("content", "")
            if not isinstance(content, str):
                raise ValueError("'content' must be text.")
            record["content"] = content
        return record

    @staticmethod
    def _text_or_default(body: JsonObject, field: str, default: str) -> str:
        value = body.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' must be text.")
        return value.strip()

    @classmethod
    def _positive_integer(cls, body: JsonObject, field: str, *, default: int) -> int:
        value = cls._integer(body, field, default=default)
        if value <= 0:
            raise ValueError(f"'{field}' must be greater than zero.")
        return value

    @staticmethod
    def _boolean(body: JsonObject, field: str, *, default: bool) -> bool:
        value = body.get(field, default)
        if not isinstance(value, bool):
            raise ValueError(f"'{field}' must be true or false.")
        return value
