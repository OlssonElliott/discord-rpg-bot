"""Framework-neutral JSON API for the local DM dashboard."""

from dataclasses import asdict
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from .dungeon import ConnectionType, TrapDamageType, TrapState
from .inventory import ItemTemplate, ItemType, WeaponGrip
from .room_images import InvalidRoomImageError, RoomImageStore
from .world import (
    AreaGraph,
    EntityKind,
    InventoryHolder,
    Room,
    RoomEditorNode,
    WorldError,
)
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


def _node_data(node: RoomEditorNode, room_images: RoomImageStore) -> JsonObject:
    room = node.room
    stored_image = room_images.path_for(room.scene_image_path)
    if stored_image is not None:
        image_version = stored_image.stem
        room_image_url = (
            f"/api/rooms/{quote(room.id, safe='')}/image"
            f"?version={quote(image_version, safe='')}"
        )
    else:
        room_image_url = room.scene_image_url
    return {
        "id": room.id,
        "area_id": room.area_id,
        "name": room.name,
        "description": room.description or "",
        "room_image_url": room_image_url,
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


def _graph_data(graph: AreaGraph, room_images: RoomImageStore) -> JsonObject:
    return {
        "area": {
            "id": graph.area.id,
            "name": graph.area.name,
            "description": graph.area.description or "",
        },
        "nodes": [_node_data(node, room_images) for node in graph.nodes],
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

    def __init__(
        self,
        world: WorldService,
        room_images: RoomImageStore | None = None,
    ) -> None:
        self.world = world
        self.room_images = room_images or RoomImageStore()

    def upload_room_image(
        self,
        room_id: str,
        content: bytes,
        content_type: str,
        original_filename: str | None = None,
    ) -> ApiResponse:
        """Validate, persist, and atomically associate a room image."""
        room = self.world.get_room(room_id)
        if room is None:
            return 404, {"error": f"Room '{room_id}' does not exist."}
        try:
            new_key = self.room_images.save(
                content, content_type, original_filename
            )
            try:
                updated = self.world.set_room_scene_image(room_id, new_key)
            except Exception:
                self.room_images.remove(new_key)
                raise
            self.room_images.remove(room.scene_image_path)
            return 200, self._room_image_data(updated)
        except (InvalidRoomImageError, ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def room_image_path(self, room_id: str) -> Path | None:
        room = self.world.get_room(room_id)
        if room is None:
            return None
        return self.room_images.path_for(room.scene_image_path)

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
            return 200, _graph_data(
                self.world.area_graph(match.group(1)), self.room_images
            )

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

        match = re.fullmatch(r"/api/rooms/([^/]+)/image", path)
        if match and method == "DELETE":
            room = self.world.get_room(match.group(1))
            if room is None:
                return 404, {"error": f"Room '{match.group(1)}' does not exist."}
            self.world.set_room_scene_image(room.id, None)
            self.room_images.remove(room.scene_image_path)
            return 200, {"id": room.id, "room_image_url": None}

        match = re.fullmatch(r"/api/rooms/([^/]+)", path)
        if match and method == "PATCH":
            room = self.world.update_room(
                match.group(1),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 200, {"id": room.id, "name": room.name, "description": room.description or ""}
        if match and method == "DELETE":
            room = self.world.get_room(match.group(1))
            self.world.delete_room(match.group(1))
            if room is not None:
                self.room_images.remove(room.scene_image_path)
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

        match = re.fullmatch(r"/api/rooms/([^/]+)/entities/([^/]+)", path)
        if match and method == "DELETE":
            room_id, entity_id = match.groups()
            room = self.world.get_room(room_id)
            if room is None:
                raise ValueError(f"Room '{room_id}' does not exist.")
            if not any(entity.id == entity_id for entity in room.entities):
                raise ValueError(
                    f"Entity '{entity_id}' does not exist in room '{room_id}'."
                )
            self.world.remove_entity(entity_id)
            return 200, {"deleted": entity_id}

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

        match = re.fullmatch(r"/api/rooms/([^/]+)/items/([^/]+)", path)
        if match and method == "DELETE":
            room_id, item_id = match.groups()
            self.world.remove_item(InventoryHolder.room(room_id), item_id)
            return 200, {"deleted": item_id}

        if path == "/api/connections" and method == "POST":
            exit_name = self._text(body, "exit_name")
            connection_type = self._connection_type(
                body, default=ConnectionType.HALLWAY
            )
            is_locked = self._boolean(body, "is_locked", default=False)
            is_broken = self._boolean(body, "is_broken", default=False)
            has_lock = self._boolean(
                body, "has_lock", default=is_locked or is_broken
            )
            unlock_difficulty = (
                self._integer(body, "unlock_difficulty", default=10)
                if is_locked
                else None
            )
            self._validate_door_lock(
                connection_type, has_lock, is_locked, is_broken, unlock_difficulty
            )
            is_open = self._boolean(body, "is_open", default=False)
            self._validate_door_open(connection_type, is_open, is_locked)
            has_trap = self._boolean(body, "has_trap", default=False)
            trap_state = (
                self._trap_state(body, default=TrapState.ARMED)
                if has_trap
                else None
            )
            trap_detection_difficulty = (
                self._integer(body, "trap_detection_difficulty", default=10)
                if has_trap
                else None
            )
            trap_damage_type = (
                self._trap_damage_type(body, default=TrapDamageType.PHYSICAL)
                if has_trap
                else None
            )
            trap_damage = (
                self._integer(body, "trap_damage", default=1)
                if has_trap
                else None
            )
            self._validate_trap(
                has_trap,
                trap_detection_difficulty,
                trap_damage_type,
                trap_damage,
            )
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
                connection_type=connection_type,
                has_lock=has_lock,
                is_locked=is_locked,
                is_broken=is_broken,
                is_open=is_open,
                unlock_difficulty=unlock_difficulty,
                has_trap=has_trap,
                trap_state=trap_state,
                trap_detection_difficulty=trap_detection_difficulty,
                trap_damage_type=trap_damage_type,
                trap_damage=trap_damage,
            )
            return 201, {
                "source_room_id": body["source_room_id"],
                "exit_name": exit_name,
                "destination_room_id": body["destination_room_id"],
                "return_exit_name": return_exit_name,
                "bidirectional": bidirectional,
                "connection_type": connection_type.value,
                "has_lock": has_lock,
                "is_locked": is_locked,
                "is_broken": is_broken,
                "is_open": is_open,
                "unlock_difficulty": unlock_difficulty,
                "has_trap": has_trap,
                "trap_state": trap_state.value if trap_state is not None else None,
                "trap_detection_difficulty": trap_detection_difficulty,
                "trap_damage_type": (
                    trap_damage_type.value if trap_damage_type is not None else None
                ),
                "trap_damage": trap_damage,
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
            connection_type = (
                self._connection_type(body) if "connection_type" in body else None
            )
            open_was_supplied = "is_open" in body
            is_open = self._boolean(body, "is_open", default=False)
            lock_was_supplied = (
                "has_lock" in body
                or "is_locked" in body
                or "is_broken" in body
                or "unlock_difficulty" in body
            )
            is_locked = self._boolean(body, "is_locked", default=False)
            is_broken = self._boolean(body, "is_broken", default=False)
            has_lock = self._boolean(
                body, "has_lock", default=is_locked or is_broken
            )
            unlock_difficulty = (
                self._integer(body, "unlock_difficulty", default=10)
                if is_locked
                else None
            )
            trap_was_supplied = any(
                field in body
                for field in (
                    "has_trap",
                    "trap_state",
                    "trap_detection_difficulty",
                    "trap_damage_type",
                    "trap_damage",
                )
            )
            has_trap = self._boolean(body, "has_trap", default=False)
            trap_state = (
                self._trap_state(body, default=TrapState.ARMED)
                if has_trap
                else None
            )
            trap_detection_difficulty = (
                self._integer(body, "trap_detection_difficulty", default=10)
                if has_trap
                else None
            )
            trap_damage_type = (
                self._trap_damage_type(body, default=TrapDamageType.PHYSICAL)
                if has_trap
                else None
            )
            trap_damage = (
                self._integer(body, "trap_damage", default=1)
                if has_trap
                else None
            )
            if is_locked and not 1 <= unlock_difficulty <= 30:
                raise ValueError("Unlock difficulty must be an integer from 1 to 30.")
            if connection_type is not None:
                self._validate_door_lock(
                    connection_type, has_lock, is_locked, is_broken,
                    unlock_difficulty
                )
                self._validate_door_open(connection_type, is_open, is_locked)
            elif is_open and is_locked:
                raise ValueError("A locked door cannot be open.")
            if trap_was_supplied:
                self._validate_trap(
                    has_trap,
                    trap_detection_difficulty,
                    trap_damage_type,
                    trap_damage,
                )
            self.world.set_connection_direction(
                source_room_id,
                exit_name,
                bidirectional=bidirectional,
                return_exit_name=return_exit_name,
            )
            if connection_type is not None:
                self.world.set_connection_type(
                    source_room_id, exit_name, connection_type
                )
            if lock_was_supplied:
                self.world.set_connection_lock(
                    source_room_id,
                    exit_name,
                    has_lock=has_lock,
                    is_locked=is_locked,
                    is_broken=is_broken,
                    unlock_difficulty=unlock_difficulty,
                )
            if open_was_supplied:
                self.world.set_connection_open(
                    source_room_id,
                    exit_name,
                    is_open=is_open,
                )
            if trap_was_supplied:
                self.world.set_connection_trap(
                    source_room_id,
                    exit_name,
                    has_trap=has_trap,
                    trap_state=trap_state,
                    trap_detection_difficulty=trap_detection_difficulty,
                    trap_damage_type=trap_damage_type,
                    trap_damage=trap_damage,
                )
            return 200, {
                "source_room_id": source_room_id,
                "exit_name": exit_name,
                "bidirectional": bidirectional,
                "return_exit_name": return_exit_name,
                **(
                    {"is_open": is_open} if open_was_supplied else {}
                ),
                **(
                    {"connection_type": connection_type.value}
                    if connection_type is not None
                    else {}
                ),
                **(
                    {
                        "has_trap": has_trap,
                        "trap_state": (
                            trap_state.value if trap_state is not None else None
                        ),
                        "trap_detection_difficulty": trap_detection_difficulty,
                        "trap_damage_type": (
                            trap_damage_type.value
                            if trap_damage_type is not None
                            else None
                        ),
                        "trap_damage": trap_damage,
                    }
                    if trap_was_supplied
                    else {}
                ),
                **(
                    {
                        "has_lock": has_lock,
                        "is_locked": is_locked,
                        "is_broken": is_broken,
                        "unlock_difficulty": unlock_difficulty,
                    }
                    if lock_was_supplied
                    else {}
                ),
            }
        if path == "/api/connections" and method == "DELETE":
            self.world.disconnect_connection(
                self._text(body, "source_room_id"), self._text(body, "exit_name")
            )
            return 200, {"deleted": True}

        return 404, {"error": "Not found."}

    def _room_image_data(self, room: Room) -> JsonObject:
        path = self.room_images.path_for(room.scene_image_path)
        return {
            "id": room.id,
            "room_image_url": (
                f"/api/rooms/{quote(room.id, safe='')}/image"
                f"?version={quote(path.stem, safe='')}"
                if path is not None
                else room.scene_image_url
            ),
        }

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
    def _connection_type(
        body: JsonObject,
        *,
        default: ConnectionType | None = None,
    ) -> ConnectionType:
        value = body.get("connection_type")
        if value is None and default is not None:
            return default
        try:
            connection_type = ConnectionType(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Connection type must be door or hallway.") from error
        if connection_type not in (ConnectionType.DOOR, ConnectionType.HALLWAY):
            raise ValueError("Connection type must be door or hallway.")
        return connection_type

    @staticmethod
    def _validate_door_lock(
        connection_type: ConnectionType,
        has_lock: bool,
        is_locked: bool,
        is_broken: bool,
        unlock_difficulty: int | None,
    ) -> None:
        if has_lock and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can have a lock.")
        if (is_locked or is_broken) and not has_lock:
            raise ValueError("A door without a lock cannot be locked or broken.")
        if is_locked and is_broken:
            raise ValueError("A broken lock cannot also be locked.")
        if is_locked and (
            unlock_difficulty is None or not 1 <= unlock_difficulty <= 30
        ):
            raise ValueError("Unlock difficulty must be an integer from 1 to 30.")

    @staticmethod
    def _validate_door_open(
        connection_type: ConnectionType,
        is_open: bool,
        is_locked: bool,
    ) -> None:
        if is_open and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can be open.")
        if is_open and is_locked:
            raise ValueError("A locked door cannot be open.")

    @staticmethod
    def _trap_damage_type(
        body: JsonObject,
        *,
        default: TrapDamageType,
    ) -> TrapDamageType:
        value = body.get("trap_damage_type", default.value)
        try:
            return TrapDamageType(value)
        except (TypeError, ValueError) as error:
            allowed = ", ".join(item.value for item in TrapDamageType)
            raise ValueError(f"Trap damage type must be one of: {allowed}.") from error

    @staticmethod
    def _trap_state(
        body: JsonObject,
        *,
        default: TrapState,
    ) -> TrapState:
        value = body.get("trap_state", default.value)
        try:
            return TrapState(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Trap state must be armed, disarmed, or triggered."
            ) from error

    @staticmethod
    def _validate_trap(
        has_trap: bool,
        trap_detection_difficulty: int | None,
        trap_damage_type: TrapDamageType | None,
        trap_damage: int | None,
    ) -> None:
        if not has_trap:
            return
        if (
            trap_detection_difficulty is None
            or not 1 <= trap_detection_difficulty <= 30
        ):
            raise ValueError("Trap detection difficulty must be an integer from 1 to 30.")
        if trap_damage_type is None:
            raise ValueError("Trap damage type is required.")
        if trap_damage is None or trap_damage <= 0:
            raise ValueError("Trap damage must be a positive integer.")

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
                "Item type must be weapon, armor, clothing, container, consumable, "
                "readable, tool, or misc."
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
