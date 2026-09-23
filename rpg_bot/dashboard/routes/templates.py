"""Template request routing for the local DM dashboard API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..serializers.common import (
    _container_template_data,
    _enemy_template_data,
    _room_feature_template_data,
    _template_data,
)
from ..parsing.template import enemy_template_from_body, item_record
from ..parsing.request import (
    parse_boolean,
    parse_integer,
    parse_optional_text,
    parse_text,
)

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_template_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle dashboard template routes, returning None for unrelated requests."""
    if method == "GET" and path == "/api/items":
        return 200, [
            _template_data(template)
            for template in sorted(
                api.world.list_item_templates(),
                key=lambda template: (
                    template.name.casefold(),
                    template.template_id,
                ),
            )
        ]

    if method == "POST" and path == "/api/items":
        record = item_record(body)
        template = api.world.create_item_template(record)
        return 201, _template_data(template)

    match = re.fullmatch(r"/api/items/([^/]+)", path)
    if method == "PUT" and match:
        record = item_record({**body, "id": match.group(1)})
        template = api.world.update_item_template(match.group(1), record)
        return 200, _template_data(template)

    if method == "GET" and path == "/api/container-templates":
        return 200, [
            _container_template_data(template)
            for template in api.world.list_container_templates()
        ]

    if method == "POST" and path == "/api/container-templates":
        default_is_locked = parse_boolean(
            body, "default_is_locked", default=False
        )
        default_is_broken = parse_boolean(
            body, "default_is_broken", default=False
        )
        default_has_lock = parse_boolean(
            body,
            "default_has_lock",
            default=default_is_locked or default_is_broken,
        )
        default_hidden = parse_boolean(
            body, "default_hidden", default=False
        )
        template = api.world.create_container_template(
            parse_text(body, "id"),
            parse_text(body, "name"),
            parse_text(body, "type"),
            parse_optional_text(body, "description"),
            default_has_lock=default_has_lock,
            default_is_locked=default_is_locked,
            default_is_broken=default_is_broken,
            default_unlock_difficulty=(
                parse_integer(
                    body, "default_unlock_difficulty", default=10
                )
                if default_is_locked
                else None
            ),
            default_hidden=default_hidden,
            default_discovery_difficulty=(
                parse_integer(
                    body, "default_discovery_difficulty", default=10
                )
                if default_hidden
                else None
            ),
        )
        return 201, _container_template_data(template)

    match = re.fullmatch(r"/api/container-templates/([^/]+)", path)
    if method == "PUT" and match:
        current = api.world.get_container_template(match.group(1))
        if current is None:
            raise ValueError(
                f"Container template '{match.group(1)}' does not exist."
            )
        default_is_locked = parse_boolean(
            body,
            "default_is_locked",
            default=current.default_is_locked,
        )
        default_is_broken = parse_boolean(
            body,
            "default_is_broken",
            default=current.default_is_broken,
        )
        default_has_lock = parse_boolean(
            body,
            "default_has_lock",
            default=current.default_has_lock,
        )
        default_hidden = parse_boolean(
            body,
            "default_hidden",
            default=current.default_hidden,
        )
        template = api.world.update_container_template(
            match.group(1),
            parse_text(body, "name")
            if "name" in body
            else current.name,
            parse_text(body, "type")
            if "type" in body
            else current.container_type.value,
            (
                parse_optional_text(body, "description")
                if "description" in body
                else current.description
            ),
            default_has_lock=default_has_lock,
            default_is_locked=default_is_locked,
            default_is_broken=default_is_broken,
            default_unlock_difficulty=(
                parse_integer(
                    body,
                    "default_unlock_difficulty",
                    default=current.default_unlock_difficulty or 10,
                )
                if default_is_locked
                else None
            ),
            default_hidden=default_hidden,
            default_discovery_difficulty=(
                parse_integer(
                    body,
                    "default_discovery_difficulty",
                    default=current.default_discovery_difficulty or 10,
                )
                if default_hidden
                else None
            ),
        )
        return 200, _container_template_data(template)

    if method == "GET" and path == "/api/enemy-templates":
        return 200, [
            _enemy_template_data(template)
            for template in api.world.list_enemy_templates()
        ]

    if method == "POST" and path == "/api/enemy-templates":
        template = api.world.create_enemy_template(
            enemy_template_from_body(body)
        )
        return 201, _enemy_template_data(template)

    match = re.fullmatch(
        r"/api/enemy-templates/([^/]+)", path
    )
    if match and method == "GET":
        template = api.world.get_enemy_template(
            match.group(1)
        )
        if template is None:
            return 404, {
                "error": (
                    f"Enemy template '{match.group(1)}' "
                    "does not exist."
                )
            }
        return 200, _enemy_template_data(template)

    if match and method == "PUT":
        current = api.world.get_enemy_template(
            match.group(1)
        )
        if current is None:
            return 404, {
                "error": (
                    f"Enemy template '{match.group(1)}' "
                    "does not exist."
                )
            }
        template = api.world.update_enemy_template(
            current.template_id,
            enemy_template_from_body(
                body,
                template_id=current.template_id,
                current=current,
            ),
        )
        return 200, _enemy_template_data(template)

    if match and method == "DELETE":
        api.world.remove_enemy_template(match.group(1))
        return 200, {"deleted": match.group(1)}

    if method == "GET" and path == "/api/room-feature-templates":
        return 200, [
            _room_feature_template_data(template)
            for template in api.world.list_room_feature_templates()
        ]

    if method == "POST" and path == "/api/room-feature-templates":
        template = api.world.create_room_feature_template(
            parse_text(body, "id"),
            parse_text(body, "name"),
            parse_text(body, "feature_type"),
            parse_optional_text(body, "description"),
        )
        return 201, _room_feature_template_data(template)

    match = re.fullmatch(r"/api/room-feature-templates/([^/]+)", path)
    if match and method == "GET":
        template = api.world.get_room_feature_template(match.group(1))
        if template is None:
            return 404, {
                "error": (
                    f"Room feature template '{match.group(1)}' does not exist."
                )
            }
        return 200, _room_feature_template_data(template)

    if match and method == "PATCH":
        current = api.world.get_room_feature_template(match.group(1))
        if current is None:
            return 404, {
                "error": (
                    f"Room feature template '{match.group(1)}' does not exist."
                )
            }
        template = api.world.update_room_feature_template(
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
            feature_type=(
                parse_text(body, "feature_type")
                if "feature_type" in body
                else current.feature_type.value
            ),
        )
        return 200, _room_feature_template_data(template)

    if match and method == "DELETE":
        current = api.world.get_room_feature_template(match.group(1))
        if current is None:
            return 404, {
                "error": (
                    f"Room feature template '{match.group(1)}' does not exist."
                )
            }
        api.world.remove_room_feature_template(current.id)
        return 200, {"deleted": current.id}

    return None
