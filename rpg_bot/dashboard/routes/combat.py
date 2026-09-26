"""Combat request routing for the local DM dashboard API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..parsing.request import (
    parse_boolean,
    parse_integer,
    parse_number,
    parse_optional_text,
    parse_text,
)
from ..serializers.combat import (
    _attack_result_data,
    _combat_state_data,
    _combatant_inspect_data,
    _enemy_attack_result_data,
)

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def _combat_guild_id(api: "DashboardAPI") -> int:
    guild_id = api.guild_id
    if guild_id is None or guild_id <= 0:
        raise ValueError(
            "Combat dashboard requires DISCORD_GUILD_ID or "
            "dashboard_server --guild-id."
        )
    return guild_id


def handle_combat_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle combat dashboard routes, returning None for unrelated requests."""
    if path == "/api/combat":
        guild_id = _combat_guild_id(api)
        if method == "GET":
            return 200, _combat_state_data(
                api.combat.current(guild_id),
                api.world,
            )
        if method == "POST":
            scene = api.combat.start(
                guild_id,
                parse_text(body, "room_id"),
            )
            return 201, _combat_state_data(scene, api.world)
        if method == "DELETE":
            api.combat.end(guild_id)
            return 200, _combat_state_data(None, api.world)

    if path == "/api/combat/landmarks" and method == "POST":
        scene = api.combat.add_landmark(
            _combat_guild_id(api),
            parse_text(body, "name"),
            parse_optional_text(body, "description"),
        )
        return 201, _combat_state_data(scene, api.world)

    match = re.fullmatch(r"/api/combat/landmarks/([^/]+)/auto-connect", path)
    if match and method == "POST":
        scene = api.combat.auto_connect_landmark(
            _combat_guild_id(api),
            match.group(1),
        )
        return 200, _combat_state_data(scene, api.world)

    match = re.fullmatch(r"/api/combat/landmarks/([^/]+)/routes", path)
    if match and method == "DELETE":
        scene = api.combat.disconnect_landmark_routes(
            _combat_guild_id(api),
            match.group(1),
        )
        return 200, _combat_state_data(scene, api.world)

    match = re.fullmatch(r"/api/combat/landmarks/([^/]+)", path)
    if match and method == "PATCH":
        guild_id = _combat_guild_id(api)
        landmark_id = match.group(1)
        scene = None
        if "x" in body or "y" in body:
            if "x" not in body or "y" not in body:
                raise ValueError("Both 'x' and 'y' are required to move a landmark.")
            scene = api.combat.set_landmark_position(
                guild_id,
                landmark_id,
                parse_number(body, "x"),
                parse_number(body, "y"),
            )
        if "cover" in body:
            scene = api.combat.set_landmark_cover(
                guild_id,
                landmark_id,
                parse_text(body, "cover"),
            )
        if scene is None:
            raise ValueError(
                "Landmark PATCH requires position or cover."
            )
        return 200, _combat_state_data(scene, api.world)
    if match and method == "DELETE":
        scene = api.combat.remove_landmark(
            _combat_guild_id(api),
            match.group(1),
        )
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/routes/auto-connect" and method == "POST":
        scene = api.combat.auto_connect_all(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/routes/all" and method == "DELETE":
        scene = api.combat.disconnect_all_routes(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/routes" and method == "PUT":
        scene = api.combat.connect_landmarks(
            _combat_guild_id(api),
            parse_text(body, "source_landmark_id"),
            parse_text(body, "destination_landmark_id"),
            parse_text(body, "distance"),
            terrain=parse_text(body, "terrain"),
            base_blocked=parse_boolean(body, "base_blocked", default=False),
        )
        return 200, _combat_state_data(scene, api.world)
    if path == "/api/combat/routes" and method == "DELETE":
        scene = api.combat.disconnect_landmarks(
            _combat_guild_id(api),
            parse_text(body, "source_landmark_id"),
            parse_text(body, "destination_landmark_id"),
        )
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/enemies" and method == "POST":
        scene = api.combat.add_enemies(
            _combat_guild_id(api),
            parse_text(body, "template_id"),
            landmark_id=parse_optional_text(body, "landmark_id"),
            quantity=parse_integer(body, "quantity", default=1),
        )
        return 201, _combat_state_data(scene, api.world)

    if path == "/api/combat/turn/next" and method == "POST":
        scene = api.combat.next_turn(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)
    if path == "/api/combat/turn/previous" and method == "POST":
        scene = api.combat.previous_turn(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)
    if path == "/api/combat/turn" and method == "PUT":
        scene = api.combat.jump_turn(
            _combat_guild_id(api),
            parse_text(body, "kind"),
            parse_text(body, "source_id"),
        )
        return 200, _combat_state_data(scene, api.world)

    initiative_match = re.fullmatch(
        r"/api/combat/initiative/(character|enemy)/([^/]+)",
        path,
    )
    if initiative_match and method == "PATCH":
        kind, source_id = initiative_match.groups()
        if "initiative_score" not in body:
            raise ValueError("'initiative_score' is required.")
        scene = api.combat.set_initiative(
            _combat_guild_id(api),
            kind,
            source_id,
            parse_integer(body, "initiative_score", default=0),
        )
        return 200, _combat_state_data(scene, api.world)

    inspect_match = re.fullmatch(
        r"/api/combat/combatants/(character|enemy)/([^/]+)/inspect",
        path,
    )
    if inspect_match and method == "GET":
        kind, source_id = inspect_match.groups()
        scene = api.combat.current(_combat_guild_id(api))
        if scene is None:
            return 404, {"error": "There is no active combat scene."}
        if not any(
            combatant.kind.value == kind
            and combatant.source_id == source_id
            for combatant in scene.combatants
        ):
            return 404, {
                "error": (
                    f"Combatant '{kind}:{source_id}' is not in the active combat."
                )
            }
        data = _combatant_inspect_data(
            api.world,
            kind,
            source_id,
            scene.room_id,
        )
        if data is None:
            return 404, {
                "error": (
                    f"Combatant '{kind}:{source_id}' could not be inspected."
                )
            }
        return 200, data

    if path == "/api/combat/actions/dash" and method == "POST":
        scene = api.combat.dash(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/actions/defend" and method == "POST":
        scene = api.combat.defend(_combat_guild_id(api))
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/actions/use-item" and method == "POST":
        scene = api.combat.use_item(
            _combat_guild_id(api),
            parse_text(body, "item_instance_id"),
        )
        return 200, _combat_state_data(scene, api.world)

    if path == "/api/combat/actions/attack" and method == "POST":
        scene, result = api.combat.attack_enemy(
            _combat_guild_id(api),
            parse_text(body, "target_enemy_id"),
        )
        payload = _combat_state_data(scene, api.world)
        payload["attack_result"] = _attack_result_data(result)
        return 200, payload

    if path == "/api/combat/actions/enemy-attack" and method == "POST":
        scene, result = api.combat.attack_character(
            _combat_guild_id(api),
            parse_text(body, "target_character_id"),
        )
        payload = _combat_state_data(scene, api.world)
        payload["enemy_attack_result"] = _enemy_attack_result_data(result)
        return 200, payload

    movement_match = re.fullmatch(
        r"/api/combat/movement/(character|enemy)/([^/]+)",
        path,
    )
    if movement_match and method == "PATCH":
        kind, source_id = movement_match.groups()
        scene = api.combat.move_combatant_toward(
            _combat_guild_id(api),
            kind,
            source_id,
            parse_text(body, "landmark_id"),
            parse_text(body, "relation"),
        )
        return 200, _combat_state_data(scene, api.world)

    match = re.fullmatch(
        r"/api/combat/combatants/(character|enemy)/([^/]+)",
        path,
    )
    if match and method == "PATCH":
        kind, source_id = match.groups()
        scene = api.combat.move_combatant(
            _combat_guild_id(api),
            kind,
            source_id,
            parse_text(body, "landmark_id"),
            parse_text(body, "relation"),
        )
        return 200, _combat_state_data(scene, api.world)
    if match and method == "DELETE":
        kind, source_id = match.groups()
        if kind != "enemy":
            raise ValueError(
                "Characters cannot be removed from combat through this endpoint."
            )
        scene = api.combat.remove_enemy(
            _combat_guild_id(api),
            source_id,
        )
        return 200, _combat_state_data(scene, api.world)

    return None
