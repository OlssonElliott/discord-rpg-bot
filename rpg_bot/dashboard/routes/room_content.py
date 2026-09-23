"""Room content request routing for the local DM dashboard API."""

from __future__ import annotations

from dataclasses import asdict
import re
from typing import TYPE_CHECKING, Any

from ...world import EntityKind, InventoryHolder
from ..parsing.request import (
    parse_integer,
    parse_optional_text,
    parse_text,
)
from ..serializers.common import _enemy_data, _stack_data

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_room_content_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle enemy, generic entity, and loose room-item routes."""
    match = re.fullmatch(
        r"/api/rooms/([^/]+)/enemies",
        path,
    )
    if match and method == "POST":
        enemy = api.world.place_enemy(
            match.group(1),
            parse_text(body, "template_id"),
            instance_id=parse_optional_text(body, "id"),
            name=parse_optional_text(body, "name"),
            description=parse_optional_text(
                body,
                "description",
            ),
        )
        template = api.world.get_enemy_template(
            enemy.template_id
        )
        assert template is not None
        return 201, _enemy_data(enemy, template)

    match = re.fullmatch(r"/api/enemies/([^/]+)", path)
    if match and method == "GET":
        enemy = api.world.get_enemy(match.group(1))
        if enemy is None:
            return 404, {
                "error": (
                    f"Enemy '{match.group(1)}' does not exist."
                )
            }
        template = api.world.get_enemy_template(
            enemy.template_id
        )
        assert template is not None
        return 200, _enemy_data(enemy, template)

    if match and method == "PATCH":
        current = api.world.get_enemy(match.group(1))
        if current is None:
            return 404, {
                "error": (
                    f"Enemy '{match.group(1)}' does not exist."
                )
            }
        enemy = api.world.update_enemy(
            current.id,
            name=(
                parse_text(body, "name")
                if "name" in body
                else current.name
            ),
            description=(
                parse_optional_text(body, "description")
                if "description" in body
                else current.description
            ),
            current_hp=parse_integer(
                body,
                "current_hp",
                default=current.current_hp,
            ),
            status=(
                parse_optional_text(body, "status")
                if "status" in body
                else None
            ),
        )
        template = api.world.get_enemy_template(
            enemy.template_id
        )
        assert template is not None
        return 200, _enemy_data(enemy, template)

    if match and method == "DELETE":
        current = api.world.get_enemy(match.group(1))
        if current is None:
            return 404, {
                "error": (
                    f"Enemy '{match.group(1)}' does not exist."
                )
            }
        api.world.remove_entity(current.id)
        return 200, {"deleted": current.id}

    match = re.fullmatch(r"/api/rooms/([^/]+)/entities", path)
    if match and method == "POST":
        try:
            kind = EntityKind(parse_text(body, "kind"))
        except ValueError as error:
            raise ValueError(
                "Entity kind must be enemy, npc, or container."
            ) from error
        entity = api.world.create_entity(
            parse_text(body, "id"),
            match.group(1),
            kind,
            parse_text(body, "name"),
            parse_optional_text(body, "description"),
        )
        return 201, asdict(entity)

    match = re.fullmatch(
        r"/api/rooms/([^/]+)/entities/([^/]+)",
        path,
    )
    if match and method == "DELETE":
        room_id, entity_id = match.groups()
        room = api.world.get_room(room_id)
        if room is None:
            raise ValueError(f"Room '{room_id}' does not exist.")
        if not any(
            entity.id == entity_id
            for entity in room.entities
        ):
            raise ValueError(
                f"Entity '{entity_id}' does not exist in room '{room_id}'."
            )
        api.world.remove_entity(entity_id)
        return 200, {"deleted": entity_id}

    match = re.fullmatch(r"/api/rooms/([^/]+)/items", path)
    if match and method == "POST":
        room_id = match.group(1)
        if api.world.get_room(room_id) is None:
            raise ValueError(
                f"Room '{room_id}' does not exist."
            )
        quantity = parse_integer(body, "quantity", default=1)
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        stack = api.world.place_catalog_item(
            InventoryHolder.room(room_id),
            parse_text(body, "item_id"),
            quantity,
        )
        return 201, _stack_data(stack)

    match = re.fullmatch(
        r"/api/rooms/([^/]+)/items/([^/]+)",
        path,
    )
    if match and method == "DELETE":
        room_id, item_id = match.groups()
        api.world.remove_item(
            InventoryHolder.room(room_id),
            item_id,
        )
        return 200, {"deleted": item_id}

    return None
