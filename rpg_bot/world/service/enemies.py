"""Enemy template and instance operations for the world service."""

from __future__ import annotations

import random

from ...inventory import ItemType, WeaponGrip
from ..enemies import (
    EnemyCombatRole,
    EnemyInstance,
    EnemyStatus,
    EnemyTemplate,
)
from ..models import InventoryHolder, NotFoundError


def _weapon_damage_expression(item) -> str:
    return " + ".join(
        f"1d{part.amount}"
        for part in item.damage_parts
    ) or "1d1"


def list_enemy_templates(service) -> tuple[EnemyTemplate, ...]:
    return service.database.list_enemy_templates()


def get_enemy_template(
    service, template_id: str
) -> EnemyTemplate | None:
    return service.database.get_enemy_template(template_id)


def create_enemy_template(
    service, template: EnemyTemplate
) -> EnemyTemplate:
    service._validate_enemy_equipment_template(template)
    return service.database.create_enemy_template(template)


def update_enemy_template(
    service,
    template_id: str,
    template: EnemyTemplate,
) -> EnemyTemplate:
    service._validate_enemy_equipment_template(template)
    return service.database.update_enemy_template(
        template_id, template
    )


def remove_enemy_template(service, template_id: str) -> None:
    service.database.remove_enemy_template(template_id)


def place_enemy(
    service,
    room_id: str,
    template_id: str,
    *,
    instance_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    combat_role: EnemyCombatRole | str | None = None,
) -> EnemyInstance:
    template = service.database.get_enemy_template(template_id)
    if template is None:
        raise NotFoundError(
            f"Enemy template '{template_id}' does not exist."
        )

    service._validate_enemy_equipment_template(template)

    melee_pool = list(template.melee_weapon_ids)
    ranged_pool = list(template.ranged_weapon_ids)
    if template.main_hand_item_id is not None:
        legacy_weapon = service.catalog.get(template.main_hand_item_id)
        legacy_pool = ranged_pool if legacy_weapon.range > 0 else melee_pool
        if template.main_hand_item_id not in legacy_pool:
            legacy_pool.append(template.main_hand_item_id)

    available_roles: list[EnemyCombatRole] = []
    if melee_pool or template.natural_attacks:
        available_roles.append(EnemyCombatRole.MELEE)
    if ranged_pool:
        available_roles.append(EnemyCombatRole.RANGED)
    if template.spell_names:
        available_roles.append(EnemyCombatRole.SPELLCASTER)
    if not available_roles:
        available_roles.append(EnemyCombatRole.MELEE)

    if combat_role is None or combat_role == "random":
        resolved_role = random.choice(available_roles)
    else:
        try:
            resolved_role = (
                combat_role
                if isinstance(combat_role, EnemyCombatRole)
                else EnemyCombatRole(combat_role)
            )
        except ValueError as error:
            raise ValueError(
                "Enemy combat role must be melee, ranged, spellcaster, or random."
            ) from error
        if resolved_role not in available_roles:
            raise ValueError(
                f"{template.name} does not support the "
                f"{resolved_role.value} role."
            )

    main_hand_item_id = None
    selected_spell = None
    selected_natural_attack = None
    if resolved_role is EnemyCombatRole.MELEE and melee_pool:
        main_hand_item_id = random.choice(melee_pool)
    elif resolved_role is EnemyCombatRole.MELEE and template.natural_attacks:
        selected_natural_attack = random.choice(template.natural_attacks)
    elif resolved_role is EnemyCombatRole.RANGED and ranged_pool:
        main_hand_item_id = random.choice(ranged_pool)
    elif resolved_role is EnemyCombatRole.SPELLCASTER:
        selected_spell = random.choice(template.spell_names)

    off_hand_pool = list(template.off_hand_item_ids)
    if template.off_hand_item_id is not None:
        if template.off_hand_item_id not in off_hand_pool:
            off_hand_pool.append(template.off_hand_item_id)
    armor_pool = list(template.armor_item_ids)
    if template.armor_item_id is not None:
        if template.armor_item_id not in armor_pool:
            armor_pool.append(template.armor_item_id)

    off_hand_item_id = (
        random.choice(off_hand_pool)
        if (
            resolved_role is EnemyCombatRole.MELEE
            and template.dual_wield
            and main_hand_item_id is not None
            and off_hand_pool
        )
        else None
    )
    armor_item_id = random.choice(armor_pool) if armor_pool else None

    enemy = service.database.create_enemy_instance(
        room_id,
        template_id,
        instance_id=instance_id,
        name=name,
        description=description,
        combat_role=resolved_role.value,
        main_hand_item_id=main_hand_item_id,
        off_hand_item_id=off_hand_item_id,
        armor_item_id=armor_item_id,
        selected_spell=selected_spell,
        selected_natural_attack=selected_natural_attack,
    )

    try:
        equipment_ids = dict.fromkeys(
            item_id
            for item_id in (
                main_hand_item_id,
                off_hand_item_id,
                armor_item_id,
            )
            if item_id is not None
        )
        for item_id in equipment_ids:
            service.place_catalog_item(
                InventoryHolder.entity(enemy.id),
                item_id,
            )
    except Exception:
        service.database.remove_world_entity(enemy.id)
        raise

    return enemy


def get_enemy(
    service, enemy_id: str
) -> EnemyInstance | None:
    return service.database.get_enemy_instance(enemy_id)


def list_room_enemies(
    service, room_id: str
) -> tuple[EnemyInstance, ...]:
    return service.database.list_room_enemy_instances(room_id)


def update_enemy(
    service,
    enemy_id: str,
    *,
    name: str,
    description: str | None,
    current_hp: int,
    status: EnemyStatus | str | None = None,
) -> EnemyInstance:
    current = service.database.get_enemy_instance(enemy_id)
    if current is None:
        raise NotFoundError(
            f"Enemy '{enemy_id}' does not exist."
        )

    if status is None:
        parsed_status = (
            EnemyStatus.DEAD
            if current_hp == 0
            else current.status
        )
    else:
        try:
            parsed_status = (
                status
                if isinstance(status, EnemyStatus)
                else EnemyStatus(status)
            )
        except ValueError as error:
            raise ValueError(
                "Enemy status must be active, dead, or fled."
            ) from error

    return service.database.update_enemy_instance(
        EnemyInstance(
            id=current.id,
            room_id=current.room_id,
            template_id=current.template_id,
            name=name,
            current_hp=current_hp,
            status=parsed_status,
            description=description,
            combat_role=current.combat_role,
            main_hand_item_id=current.main_hand_item_id,
            off_hand_item_id=current.off_hand_item_id,
            armor_item_id=current.armor_item_id,
            selected_spell=current.selected_spell,
            selected_natural_attack=current.selected_natural_attack,
        )
    )


def validate_enemy_equipment_template(
    service,
    template: EnemyTemplate,
) -> None:
    equipment = [
        ("main hand", template.main_hand_item_id, ItemType.WEAPON, None),
        ("off hand", template.off_hand_item_id, ItemType.WEAPON, "offhand"),
        ("armor", template.armor_item_id, ItemType.ARMOR, "armor"),
        *(
            ("melee weapon", item_id, ItemType.WEAPON, "melee")
            for item_id in template.melee_weapon_ids
        ),
        *(
            ("ranged weapon", item_id, ItemType.WEAPON, "ranged")
            for item_id in template.ranged_weapon_ids
        ),
        *(
            ("off-hand", item_id, ItemType.WEAPON, "offhand")
            for item_id in template.off_hand_item_ids
        ),
        *(
            ("armor", item_id, ItemType.ARMOR, "armor")
            for item_id in template.armor_item_ids
        ),
    ]

    for label, item_id, expected_type, expected_range in equipment:
        if item_id is None:
            continue

        try:
            item = service.catalog.get(item_id)
        except ValueError as error:
            raise ValueError(
                f"Enemy {label} item '{item_id}' does not exist."
            ) from error

        if item.item_type is not expected_type:
            raise ValueError(
                f"Enemy {label} item '{item_id}' must be "
                f"{expected_type.value}."
            )
        if expected_range == "melee" and item.range > 0:
            raise ValueError(
                f"Enemy melee weapon '{item_id}' must have Range 0."
            )
        if expected_range == "ranged" and item.range <= 0:
            raise ValueError(
                f"Enemy ranged weapon '{item_id}' must have Range above 0."
            )
        if expected_range == "offhand":
            if (
                item.range > 0
                or item.grip is not WeaponGrip.ONE_HANDED
            ):
                raise ValueError(
                    f"Enemy off-hand weapon '{item_id}' must be "
                    "a one-handed melee weapon."
                )
        if expected_range == "armor":
            if (
                template.armor_reduction_filter is not None
                and item.protection != template.armor_reduction_filter
            ):
                raise ValueError(
                    f"Enemy armor '{item_id}' protection "
                    f"{item.protection} does not match the selected "
                    f"damage reduction {template.armor_reduction_filter}."
                )

        damage_filter = (
            template.melee_damage_filter
            if expected_range == "melee"
            else template.ranged_damage_filter
            if expected_range == "ranged"
            else None
        )
        if (
            damage_filter is not None
            and _weapon_damage_expression(item) != damage_filter
        ):
            raise ValueError(
                f"Enemy {label} '{item_id}' damage "
                f"{_weapon_damage_expression(item)} does not match "
                f"the selected damage filter {damage_filter}."
            )


class WorldEnemyMixin:
    list_enemy_templates = list_enemy_templates
    get_enemy_template = get_enemy_template
    create_enemy_template = create_enemy_template
    update_enemy_template = update_enemy_template
    remove_enemy_template = remove_enemy_template
    place_enemy = place_enemy
    get_enemy = get_enemy
    list_room_enemies = list_room_enemies
    update_enemy = update_enemy
    _validate_enemy_equipment_template = validate_enemy_equipment_template
