"""Character request routing for the local DM dashboard API."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ...inventory import EquipmentSlot
from ...characters.models import CharacterCombatStatus, Stance
from ..parsing.request import (
    parse_integer,
    parse_optional_text,
    parse_text,
)
from ..serializers.common import _character_admin_data, _character_data

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_character_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle character dashboard routes, returning None for unrelated requests."""
    if method == "GET" and path == "/api/characters":
        return 200, [
            _character_data(api.world, api.portraits, character)
            for character in api.world.list_characters()
        ]

    character_match = re.fullmatch(r"/api/characters/([1-9][0-9]*)", path)
    if character_match:
        character_id = int(character_match.group(1))
        character = api.world.database.get_character_by_global_id(
            character_id
        )
        if character is None:
            return 404, {
                "error": f"Character {character_id} does not exist."
            }
        if method == "GET":
            return 200, _character_admin_data(
                api.world,
                api.portraits,
                character,
            )
        if method == "PATCH":
            state = api.world.database.get_character_combat_state(
                character_id
            )
            inventory = api.world.database.get_character_inventory(
                character_id
            )

            stance_value = body.get("stance", character.stance.value)
            try:
                stance = Stance(stance_value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Stance must be steady, bad_stance, or prone."
                ) from error

            status_value = body.get("status", state.status.value)
            try:
                status = CharacterCombatStatus(status_value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Status must be active, downed, stable, recovering, or dead."
                ) from error

            attributes_raw = body.get(
                "attributes",
                dict(character.attributes),
            )
            if not isinstance(attributes_raw, dict):
                raise ValueError("'attributes' must be an object.")
            attributes: dict[str, int] = {}
            for attribute, value in attributes_raw.items():
                if not isinstance(attribute, str):
                    raise ValueError("Attribute names must be text.")
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError("Attribute values must be integers.")
                attributes[attribute] = value

            skills_raw = body.get("skills", dict(character.skills))
            if not isinstance(skills_raw, dict):
                raise ValueError("'skills' must be an object.")
            skills: dict[str, int] = {}
            for skill, rank in skills_raw.items():
                if not isinstance(skill, str):
                    raise ValueError("Skill names must be text.")
                if isinstance(rank, bool) or not isinstance(rank, int):
                    raise ValueError("Skill ranks must be integers.")
                skills[skill] = rank

            wallet_raw = body.get(
                "wallet",
                {
                    "copper": inventory.copper,
                    "silver": inventory.silver,
                    "gold": inventory.gold,
                },
            )
            if not isinstance(wallet_raw, dict):
                raise ValueError("'wallet' must be an object.")

            current_room_id = (
                parse_optional_text(body, "current_room_id")
                if "current_room_id" in body
                else character.current_room_id
            )
            updated = api.world.database.update_character_admin(
                character_id,
                name=(
                    parse_text(body, "name")
                    if "name" in body
                    else character.name
                ),
                hp=parse_integer(body, "hp", default=character.hp),
                max_hp=parse_integer(
                    body,
                    "max_hp",
                    default=character.max_hp,
                ),
                stance=stance,
                lineage=(
                    parse_optional_text(body, "lineage")
                    if "lineage" in body
                    else character.lineage
                ),
                race=(
                    parse_optional_text(body, "race")
                    if "race" in body
                    else character.race
                ),
                age=(
                    parse_optional_text(body, "age")
                    if "age" in body
                    else character.age
                ),
                gender=(
                    parse_optional_text(body, "gender")
                    if "gender" in body
                    else character.gender
                ),
                attributes=attributes,
                skills=skills,
                status=status,
                failed_death_saves=parse_integer(
                    body,
                    "failed_death_saves",
                    default=state.failed_death_saves,
                ),
                current_room_id=current_room_id,
                copper=parse_integer(
                    wallet_raw,
                    "copper",
                    default=inventory.copper,
                ),
                silver=parse_integer(
                    wallet_raw,
                    "silver",
                    default=inventory.silver,
                ),
                gold=parse_integer(
                    wallet_raw,
                    "gold",
                    default=inventory.gold,
                ),
            )
            return 200, _character_admin_data(
                api.world,
                api.portraits,
                updated,
            )

    character_items_match = re.fullmatch(
        r"/api/characters/([1-9][0-9]*)/items",
        path,
    )
    if character_items_match and method == "POST":
        character_id = int(character_items_match.group(1))
        if api.world.database.get_character_by_global_id(character_id) is None:
            return 404, {
                "error": f"Character {character_id} does not exist."
            }
        template = api.world.catalog.get(
            parse_text(body, "template_id")
        )
        quantity = parse_integer(body, "quantity", default=1)
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        api.world.database.add_inventory_item(
            character_id,
            template.template_id,
            quantity=quantity,
            durability=template.durability,
            stackable=template.stackable,
        )
        updated = api.world.database.get_character_by_global_id(
            character_id
        )
        assert updated is not None
        return 201, _character_admin_data(
            api.world,
            api.portraits,
            updated,
        )

    character_item_match = re.fullmatch(
        r"/api/characters/([1-9][0-9]*)/items/([^/]+)",
        path,
    )
    if character_item_match and method in {"PATCH", "DELETE"}:
        character_id = int(character_item_match.group(1))
        instance_id = character_item_match.group(2)
        character = api.world.database.get_character_by_global_id(
            character_id
        )
        if character is None:
            return 404, {
                "error": f"Character {character_id} does not exist."
            }

        inventory = api.world.database.get_character_inventory(
            character_id
        )
        item = next(
            (
                candidate
                for candidate in inventory.items
                if candidate.instance_id == instance_id
            ),
            None,
        )
        if item is None:
            return 404, {"error": "That item is not in this inventory."}

        equipped_slot = next(
            (
                slot
                for slot, equipped_id in inventory.equipment.items()
                if equipped_id == instance_id
            ),
            None,
        )
        if method == "DELETE":
            quantity = 0
            durability = item.durability
            parsed_slot = None
        else:
            quantity = parse_integer(
                body,
                "quantity",
                default=item.quantity,
            )
            durability_value = body.get("durability", item.durability)
            if durability_value is not None and (
                isinstance(durability_value, bool)
                or not isinstance(durability_value, int)
            ):
                raise ValueError("'durability' must be an integer or null.")
            durability = durability_value

            if "equipped_slot" not in body:
                parsed_slot = equipped_slot
            else:
                slot_value = body.get("equipped_slot")
                if slot_value is None or slot_value == "":
                    parsed_slot = None
                else:
                    try:
                        parsed_slot = EquipmentSlot(slot_value)
                    except (TypeError, ValueError) as error:
                        raise ValueError(
                            "Unknown equipment slot."
                        ) from error

        api.world.database.set_character_inventory_item_admin(
            character_id,
            instance_id,
            quantity=quantity,
            durability=durability,
            equipped_slot=parsed_slot,
        )
        updated = api.world.database.get_character_by_global_id(
            character_id
        )
        assert updated is not None
        return 200, _character_admin_data(
            api.world,
            api.portraits,
            updated,
        )

    match = re.fullmatch(r"/api/characters/(\d+)/room", path)
    if method == "PATCH" and match:
        character_id = int(match.group(1))
        room = api.world.place_character(
            character_id, parse_text(body, "room_id")
        )
        return 200, {"id": character_id, "current_room_id": room.id}

    return None
