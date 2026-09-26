"""Template request parsing for the local DM dashboard API."""

from __future__ import annotations

from typing import Any

from ...world.enemies import EnemyTemplate
from ...inventory import ItemType, WeaponGrip
from .request import (
    parse_boolean,
    parse_integer,
    parse_optional_text,
    parse_text,
)


JsonObject = dict[str, Any]


def enemy_template_from_body(
    body: JsonObject,
    *,
    template_id: str | None = None,
    current: EnemyTemplate | None = None,
) -> EnemyTemplate:
    """Build an enemy template from dashboard request data."""

    def text_value(field: str, default: str) -> str:
        if field in body:
            return parse_text(body, field)
        return default

    def optional_value(
        field: str,
        default: str | None,
    ) -> str | None:
        if field in body:
            return parse_optional_text(body, field)
        return default

    return EnemyTemplate(
        template_id=template_id or parse_text(body, "id"),
        name=(
            parse_text(body, "name")
            if current is None or "name" in body
            else current.name
        ),
        description=optional_value(
            "description",
            current.description if current is not None else None,
        ),
        race=text_value(
            "race",
            current.race if current is not None else "Unknown",
        ),
        difficulty_level=parse_integer(
            body,
            "difficulty_level",
            default=current.difficulty_level if current is not None else 1,
        ),
        strength=parse_integer(
            body,
            "strength",
            default=current.strength if current is not None else 0,
        ),
        dexterity=parse_integer(
            body,
            "dexterity",
            default=current.dexterity if current is not None else 0,
        ),
        arcana=parse_integer(
            body,
            "arcana",
            default=current.arcana if current is not None else 0,
        ),
        vitality=parse_integer(
            body,
            "vitality",
            default=current.vitality if current is not None else 0,
        ),
        insight=parse_integer(
            body,
            "insight",
            default=current.insight if current is not None else 0,
        ),
        personality=parse_integer(
            body,
            "personality",
            default=current.personality if current is not None else 0,
        ),
        max_hp=parse_integer(
            body,
            "max_hp",
            default=current.max_hp if current is not None else 7,
        ),
        armor=parse_integer(
            body,
            "armor",
            default=current.armor if current is not None else 0,
        ),
        magical_resistance=parse_integer(
            body,
            "magical_resistance",
            default=(
                current.magical_resistance
                if current is not None
                else 0
            ),
        ),
        attack_dc=parse_integer(
            body,
            "attack_dc",
            default=current.attack_dc if current is not None else 12,
        ),
        defense_dc=parse_integer(
            body,
            "defense_dc",
            default=current.defense_dc if current is not None else 12,
        ),
        damage=text_value(
            "damage",
            current.damage if current is not None else "1d4",
        ),
        attack_profile=text_value(
            "attack_profile",
            current.attack_profile if current is not None else "Basic attack",
        ),
        special_ability=optional_value(
            "special_ability",
            current.special_ability if current is not None else None,
        ),
        typical_behaviour=text_value(
            "typical_behaviour",
            current.typical_behaviour if current is not None else "Unknown",
        ),
        main_hand_item_id=optional_value(
            "main_hand_item_id",
            current.main_hand_item_id if current is not None else None,
        ),
        off_hand_item_id=optional_value(
            "off_hand_item_id",
            current.off_hand_item_id if current is not None else None,
        ),
        armor_item_id=optional_value(
            "armor_item_id",
            current.armor_item_id if current is not None else None,
        ),
    )


def item_record(
    body: JsonObject,
) -> dict[str, object]:
    """Build an item catalog record from dashboard request data."""
    try:
        item_type = ItemType(parse_text(body, "item_type"))
    except ValueError as error:
        raise ValueError(
            "Item type must be weapon, armor, clothing, container, consumable, "
            "readable, tool, or misc."
        ) from error

    value = parse_integer(body, "value", default=0)
    weight = parse_integer(body, "weight", default=0)
    default_slot_cost = (
        0 if item_type is ItemType.READABLE and weight == 0 else 1
    )
    slot_cost = parse_integer(
        body,
        "slot_cost",
        default=default_slot_cost,
    )
    if value < 0 or weight < 0 or slot_cost < 0:
        raise ValueError(
            "Item value, weight, and slot cost cannot be negative."
        )

    record: dict[str, object] = {
        "item_type": item_type.value,
        "id": parse_text(body, "id"),
        "name": parse_text(body, "name"),
        "rarity": _text_or_default(body, "rarity", "Common"),
        "value": value,
        "description": parse_optional_text(body, "description") or "",
        "weight": weight,
        "slot_cost": slot_cost,
        "tags": [
            (
                "stackable"
                if parse_boolean(
                    body,
                    "stackable",
                    default=item_type is ItemType.CONSUMABLE,
                )
                else "not_stackable"
            )
        ],
        "modifiers": [],
        "requirements": [],
    }

    if item_type is ItemType.WEAPON:
        try:
            grip = WeaponGrip(
                _text_or_default(body, "grip", "one_handed")
            )
        except ValueError as error:
            raise ValueError(
                "Weapon grip must be one_handed or two_handed."
            ) from error
        durability = _positive_integer(
            body,
            "durability",
            default=40,
        )
        damage = _positive_integer(
            body,
            "damage",
            default=1,
        )
        weapon_range = parse_integer(
            body,
            "range",
            default=0,
        )
        if weapon_range < 0:
            raise ValueError("Weapon range cannot be negative.")
        record.update(
            grip=grip.value,
            durability=durability,
            range=weapon_range,
            damage_parts=[
                {
                    "amount": damage,
                    "damage_type": _text_or_default(
                        body,
                        "damage_type",
                        "physical",
                    ),
                }
            ],
        )
    elif item_type is ItemType.ARMOR:
        protection = _positive_integer(
            body,
            "protection",
            default=1,
        )
        strength_requirement = parse_integer(
            body,
            "strength_requirement",
            default=0,
        )
        if strength_requirement < 0:
            raise ValueError(
                "Strength requirement cannot be negative."
            )
        record.update(
            protection_current=protection,
            protection_max=protection,
            dodge_penalty=parse_integer(
                body,
                "dodge_penalty",
                default=0,
            ),
            strength_requirement=strength_requirement or None,
        )
    elif item_type is ItemType.CONTAINER:
        record.update(
            capacity=_positive_integer(
                body,
                "capacity",
                default=10,
            ),
            items=[],
            can_equip=parse_boolean(
                body,
                "can_equip",
                default=False,
            ),
            locked=False,
        )
    elif item_type is ItemType.CONSUMABLE:
        record.update(
            affected_stat="hp",
            affected_amount=_positive_integer(
                body,
                "affected_amount",
                default=1,
            ),
            side_effects=None,
        )
    elif item_type is ItemType.READABLE:
        content = body.get("content", "")
        if not isinstance(content, str):
            raise ValueError("'content' must be text.")
        record["content"] = content

    return record


def _text_or_default(
    body: JsonObject,
    field: str,
    default: str,
) -> str:
    value = body.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' must be text.")
    return value.strip()


def _positive_integer(
    body: JsonObject,
    field: str,
    *,
    default: int,
) -> int:
    value = parse_integer(body, field, default=default)
    if value <= 0:
        raise ValueError(f"'{field}' must be greater than zero.")
    return value
