"""Container request routing for the local DM dashboard API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...world import InventoryHolder
from ..parsing.request import (
    parse_boolean,
    parse_integer,
    parse_optional_text,
    parse_text,
)
from ..serializers.common import _container_data, _stack_data

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_container_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle room-container and container-inventory routes."""
    match = re.fullmatch(r"/api/rooms/([^/]+)/containers", path)
    if match and method == "POST":
        room_id = match.group(1)
        template_id = parse_text(body, "template_id")
        template = api.world.get_container_template(template_id)
        if template is None:
            raise ValueError(
                f"Container template '{template_id}' does not exist."
            )
        has_lock = (
            parse_boolean(
                body,
                "has_lock",
                default=template.default_has_lock,
            )
            if "has_lock" in body
            else None
        )
        is_locked = (
            parse_boolean(
                body,
                "is_locked",
                default=template.default_is_locked,
            )
            if "is_locked" in body
            else None
        )
        is_broken = (
            parse_boolean(
                body,
                "is_broken",
                default=template.default_is_broken,
            )
            if "is_broken" in body
            else None
        )
        hidden = (
            parse_boolean(
                body,
                "hidden",
                default=template.default_hidden,
            )
            if "hidden" in body
            else None
        )
        instance = api.world.place_container(
            room_id,
            template_id,
            instance_id=parse_optional_text(body, "id"),
            name=parse_optional_text(body, "name"),
            description=(
                parse_optional_text(body, "description")
                if "description" in body
                else None
            ),
            has_lock=has_lock,
            is_locked=is_locked,
            is_broken=is_broken,
            unlock_difficulty=(
                parse_integer(
                    body,
                    "unlock_difficulty",
                    default=template.default_unlock_difficulty or 10,
                )
                if (
                    (is_locked is True)
                    or (is_locked is None and template.default_is_locked)
                )
                else None
            ),
            hidden=hidden,
            discovery_difficulty=(
                parse_integer(
                    body,
                    "discovery_difficulty",
                    default=template.default_discovery_difficulty or 10,
                )
                if (
                    (hidden is True)
                    or (hidden is None and template.default_hidden)
                )
                else None
            ),
            is_open=parse_boolean(body, "is_open", default=False),
            searched=parse_boolean(body, "searched", default=False),
        )
        return 201, _container_data(
            instance,
            api.world.inventory(
                InventoryHolder.entity(instance.id)
            ),
        )

    match = re.fullmatch(r"/api/containers/([^/]+)", path)
    if match and method == "GET":
        instance = api.world.get_container(match.group(1))
        if instance is None:
            return 404, {
                "error": f"Container '{match.group(1)}' does not exist."
            }
        return 200, _container_data(
            instance,
            api.world.inventory(
                InventoryHolder.entity(instance.id)
            ),
        )

    if match and method == "PATCH":
        current = api.world.get_container(match.group(1))
        if current is None:
            raise ValueError(
                f"Container '{match.group(1)}' does not exist."
            )
        has_lock = parse_boolean(
            body,
            "has_lock",
            default=current.has_lock,
        )
        is_locked = parse_boolean(
            body,
            "is_locked",
            default=current.is_locked,
        )
        is_broken = parse_boolean(
            body,
            "is_broken",
            default=current.is_broken,
        )
        hidden = parse_boolean(
            body,
            "hidden",
            default=current.hidden,
        )
        updated = api.world.update_container(
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
            has_lock=has_lock,
            is_locked=is_locked,
            is_broken=is_broken,
            unlock_difficulty=(
                parse_integer(
                    body,
                    "unlock_difficulty",
                    default=current.unlock_difficulty or 10,
                )
                if is_locked
                else None
            ),
            hidden=hidden,
            discovery_difficulty=(
                parse_integer(
                    body,
                    "discovery_difficulty",
                    default=current.discovery_difficulty or 10,
                )
                if hidden
                else None
            ),
            is_open=parse_boolean(
                body,
                "is_open",
                default=current.is_open,
            ),
            searched=parse_boolean(
                body,
                "searched",
                default=current.searched,
            ),
        )
        return 200, _container_data(
            updated,
            api.world.inventory(
                InventoryHolder.entity(updated.id)
            ),
        )

    if match and method == "DELETE":
        api.world.remove_container(match.group(1))
        return 200, {"deleted": match.group(1)}

    match = re.fullmatch(r"/api/containers/([^/]+)/items", path)
    if match and method == "POST":
        container_id = match.group(1)
        if api.world.get_container(container_id) is None:
            raise ValueError(
                f"Container '{container_id}' does not exist."
            )
        quantity = parse_integer(body, "quantity", default=1)
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        stack = api.world.place_catalog_item(
            InventoryHolder.entity(container_id),
            parse_text(body, "item_id"),
            quantity,
        )
        return 201, _stack_data(stack)

    match = re.fullmatch(
        r"/api/containers/([^/]+)/items/([^/]+)",
        path,
    )
    if match and method == "PUT":
        container_id, item_id = match.groups()
        quantity = parse_integer(body, "quantity", default=1)
        stack = api.world.set_item_quantity(
            InventoryHolder.entity(container_id),
            item_id,
            quantity,
        )
        return 200, _stack_data(stack)

    if match and method == "DELETE":
        container_id, item_id = match.groups()
        api.world.remove_item(
            InventoryHolder.entity(container_id),
            item_id,
        )
        return 200, {"deleted": item_id}

    return None
