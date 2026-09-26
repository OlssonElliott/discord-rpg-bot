"""World structure request routing for the local DM dashboard API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...world import InventoryHolder
from ..parsing.request import (
    parse_number,
    parse_optional_text,
    parse_text,
)
from ..serializers.common import (
    _container_data,
    _enemy_data,
    _enemy_inventory_data,
    _graph_data,
    _legacy_enemy_data,
    _room_feature_data,
)

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_world_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle area, room, and room-feature routes."""
    if method == "GET" and path == "/api/areas":
        return 200, [
            {
                "id": area.id,
                "name": area.name,
                "description": area.description or "",
                "room_count": len(area.room_ids),
            }
            for area in api.world.list_areas()
        ]

    if method == "POST" and path == "/api/areas":
        area = api.world.create_area(
            parse_text(body, "id"),
            parse_text(body, "name"),
            parse_optional_text(body, "description"),
        )
        return 201, {
            "id": area.id,
            "name": area.name,
            "description": area.description or "",
        }

    match = re.fullmatch(r"/api/areas/([^/]+)/graph", path)
    if method == "GET" and match:
        graph = _graph_data(
            api.world.area_graph(match.group(1)),
            api.room_images,
        )
        for node in graph["nodes"]:
            room_id = str(node["id"])
            containers = api.world.list_room_containers(room_id)
            node["containers"] = [
                _container_data(
                    container,
                    api.world.inventory(
                        InventoryHolder.entity(container.id)
                    ),
                )
                for container in containers
            ]
            node["counts"]["containers"] = len(containers)

            room = api.world.get_room(room_id)
            enemy_instances = {
                enemy.id: enemy
                for enemy in api.world.list_room_enemies(room_id)
            }
            enemy_data: list[JsonObject] = []
            if room is not None:
                for entity in room.enemies:
                    enemy = enemy_instances.get(entity.id)
                    if enemy is None:
                        enemy_data.append(
                            _legacy_enemy_data(entity)
                        )
                        continue
                    template = api.world.get_enemy_template(
                        enemy.template_id
                    )
                    if template is None:
                        enemy_data.append(
                            _legacy_enemy_data(entity)
                        )
                        continue
                    enemy_data.append(
                        _enemy_data(
                            enemy,
                            template,
                            inventory=_enemy_inventory_data(
                                api.world,
                                enemy,
                            ),
                        )
                    )
            node["enemies"] = enemy_data

            room_features = api.world.list_room_features(room_id)
            node["room_features"] = [
                _room_feature_data(feature)
                for feature in room_features
            ]
            node["counts"]["room_features"] = len(room_features)

        for connection in graph["connections"]:
            key = (
                str(connection["source_room_id"]),
                str(connection["exit_name"]),
            )
            if key in api._connection_trap_damage:
                connection["trap_damage"] = (
                    api._connection_trap_damage[key]
                )
        return 200, graph

    match = re.fullmatch(r"/api/areas/([^/]+)/rooms", path)
    if method == "POST" and match:
        room = api.world.create_room(
            parse_text(body, "id"),
            match.group(1),
            parse_text(body, "name"),
            parse_optional_text(body, "description"),
            editor_x=parse_number(body, "x"),
            editor_y=parse_number(body, "y"),
        )
        return 201, {"id": room.id}

    match = re.fullmatch(r"/api/rooms/([^/]+)/image", path)
    if match and method == "DELETE":
        room = api.world.get_room(match.group(1))
        if room is None:
            return 404, {
                "error": f"Room '{match.group(1)}' does not exist."
            }
        api.world.set_room_scene_image(room.id, None)
        api.room_images.remove(room.scene_image_path)
        return 200, {"id": room.id, "room_image_url": None}

    match = re.fullmatch(r"/api/rooms/([^/]+)", path)
    if match and method == "PATCH":
        room = api.world.update_room(
            match.group(1),
            parse_text(body, "name"),
            parse_optional_text(body, "description"),
        )
        return 200, {
            "id": room.id,
            "name": room.name,
            "description": room.description or "",
        }
    if match and method == "DELETE":
        room = api.world.get_room(match.group(1))
        api.world.delete_room(match.group(1))
        if room is not None:
            api.room_images.remove(room.scene_image_path)
        return 200, {"deleted": match.group(1)}

    match = re.fullmatch(r"/api/rooms/([^/]+)/position", path)
    if match and method == "PATCH":
        api.world.set_room_editor_position(
            match.group(1),
            parse_number(body, "x"),
            parse_number(body, "y"),
        )
        return 200, {
            "id": match.group(1),
            "position": {"x": body["x"], "y": body["y"]},
        }

    match = re.fullmatch(r"/api/rooms/([^/]+)/features", path)
    if match and method == "GET":
        return 200, [
            _room_feature_data(feature)
            for feature in api.world.list_room_features(match.group(1))
        ]
    if match and method == "POST":
        feature = api.world.create_room_feature(
            match.group(1),
            parse_text(body, "id"),
            parse_text(body, "name"),
            parse_text(body, "feature_type"),
            parse_optional_text(body, "description"),
        )
        return 201, _room_feature_data(feature)

    match = re.fullmatch(r"/api/room-features/([^/]+)", path)
    if match and method == "GET":
        feature = api.world.get_room_feature(match.group(1))
        if feature is None:
            return 404, {
                "error": (
                    f"Room feature '{match.group(1)}' does not exist."
                )
            }
        return 200, _room_feature_data(feature)

    if match and method == "PATCH":
        current = api.world.get_room_feature(match.group(1))
        if current is None:
            return 404, {
                "error": (
                    f"Room feature '{match.group(1)}' does not exist."
                )
            }
        feature = api.world.update_room_feature(
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
        return 200, _room_feature_data(feature)

    if match and method == "DELETE":
        api.world.remove_room_feature(match.group(1))
        return 200, {"deleted": match.group(1)}

    return None
