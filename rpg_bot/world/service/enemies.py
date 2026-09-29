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

    one_handed_melee = [
        item_id
        for item_id in melee_pool
        if service.catalog.get(item_id).grip is WeaponGrip.ONE_HANDED
    ]
    two_handed_melee = [
        item_id
        for item_id in melee_pool
        if service.catalog.get(item_id).grip is WeaponGrip.TWO_HANDED
    ]

    second_weapon_pool = list(template.off_hand_item_ids)
    shield_pool = list(template.shield_item_ids)
    if template.off_hand_item_id is not None:
        legacy_offhand = service.catalog.get(template.off_hand_item_id)
        if legacy_offhand.defense_bonus > 0:
            if template.off_hand_item_id not in shield_pool:
                shield_pool.append(template.off_hand_item_id)
        elif template.off_hand_item_id not in second_weapon_pool:
            second_weapon_pool.append(template.off_hand_item_id)

    feasible_melee_loadouts: list[str] = []
    requested_loadouts = list(template.melee_loadouts)
    if not requested_loadouts:
        if one_handed_melee:
            feasible_melee_loadouts.append("one_handed")
        if one_handed_melee and shield_pool:
            feasible_melee_loadouts.append("shield")
        if one_handed_melee and second_weapon_pool:
            feasible_melee_loadouts.append("dual_wield")
        if two_handed_melee:
            feasible_melee_loadouts.append("two_handed")
        if template.natural_attacks:
            feasible_melee_loadouts.append("natural")
    else:
        feasible_melee_loadouts = requested_loadouts

    available_roles: list[EnemyCombatRole] = []
    if feasible_melee_loadouts:
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

    race_pool = list(template.allowed_races) or [template.race]
    resolved_race = random.choice(race_pool)

    main_hand_item_id = None
    off_hand_item_id = None
    selected_spell = None
    selected_natural_attack = None
    loadout_style = None

    if resolved_role is EnemyCombatRole.MELEE:
        if not feasible_melee_loadouts:
            raise ValueError(
                f"{template.name} has no valid melee loadout."
            )
        loadout_style = random.choice(feasible_melee_loadouts)
        if loadout_style == "one_handed":
            main_hand_item_id = random.choice(one_handed_melee)
        elif loadout_style == "shield":
            main_hand_item_id = random.choice(one_handed_melee)
            off_hand_item_id = random.choice(shield_pool)
        elif loadout_style == "dual_wield":
            main_hand_item_id = random.choice(one_handed_melee)
            off_hand_item_id = random.choice(second_weapon_pool)
        elif loadout_style == "two_handed":
            main_hand_item_id = random.choice(two_handed_melee)
        elif loadout_style == "natural":
            selected_natural_attack = random.choice(
                template.natural_attacks
            )
    elif resolved_role is EnemyCombatRole.RANGED:
        loadout_style = "ranged"
        main_hand_item_id = random.choice(ranged_pool)
    elif resolved_role is EnemyCombatRole.SPELLCASTER:
        loadout_style = "spellcaster"
        selected_spell = random.choice(template.spell_names)

    armor_pool = list(template.armor_item_ids)
    if template.armor_item_id is not None:
        if template.armor_item_id not in armor_pool:
            armor_pool.append(template.armor_item_id)
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
        race=resolved_race,
        loadout_style=loadout_style,
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
            race=current.race,
            loadout_style=current.loadout_style,
        )
    )


def validate_enemy_equipment_template(
    service,
    template: EnemyTemplate,
) -> None:
    def item(item_id: str):
        try:
            return service.catalog.get(item_id)
        except ValueError as error:
            raise ValueError(
                f"Enemy equipment item '{item_id}' does not exist."
            ) from error

    melee_ids = list(template.melee_weapon_ids)
    ranged_ids = list(template.ranged_weapon_ids)
    second_weapon_ids = list(template.off_hand_item_ids)
    shield_ids = list(template.shield_item_ids)
    armor_ids = list(template.armor_item_ids)

    if template.main_hand_item_id is not None:
        legacy = item(template.main_hand_item_id)
        if legacy.item_type is not ItemType.WEAPON:
            raise ValueError("Enemy main hand item must be a weapon.")
        (ranged_ids if legacy.range > 0 else melee_ids).append(
            template.main_hand_item_id
        )
    if template.off_hand_item_id is not None:
        legacy_offhand = item(template.off_hand_item_id)
        if legacy_offhand.defense_bonus > 0:
            shield_ids.append(template.off_hand_item_id)
        else:
            second_weapon_ids.append(template.off_hand_item_id)
    if template.armor_item_id is not None:
        armor_ids.append(template.armor_item_id)

    for item_id in dict.fromkeys(melee_ids):
        weapon = item(item_id)
        if weapon.item_type is not ItemType.WEAPON or weapon.range > 0:
            raise ValueError(
                f"Enemy melee weapon '{item_id}' must be a melee weapon."
            )
        if (
            template.melee_damage_filter is not None
            and _weapon_damage_expression(weapon)
            != template.melee_damage_filter
        ):
            raise ValueError(
                f"Enemy melee weapon '{item_id}' damage "
                f"{_weapon_damage_expression(weapon)} does not match "
                f"the selected damage filter "
                f"{template.melee_damage_filter}."
            )

    for item_id in dict.fromkeys(ranged_ids):
        weapon = item(item_id)
        if weapon.item_type is not ItemType.WEAPON or weapon.range <= 0:
            raise ValueError(
                f"Enemy ranged weapon '{item_id}' must have Range above 0."
            )
        if (
            template.ranged_damage_filter is not None
            and _weapon_damage_expression(weapon)
            != template.ranged_damage_filter
        ):
            raise ValueError(
                f"Enemy ranged weapon '{item_id}' damage "
                f"{_weapon_damage_expression(weapon)} does not match "
                f"the selected damage filter "
                f"{template.ranged_damage_filter}."
            )

    for item_id in dict.fromkeys(second_weapon_ids):
        offhand = item(item_id)
        if (
            offhand.item_type is not ItemType.WEAPON
            or offhand.range > 0
            or offhand.grip is not WeaponGrip.ONE_HANDED
        ):
            raise ValueError(
                f"Enemy second weapon '{item_id}' must be "
                "a one-handed melee weapon."
            )

    for item_id in dict.fromkeys(shield_ids):
        shield = item(item_id)
        if (
            shield.item_type is not ItemType.ARMOR
            or shield.defense_bonus <= 0
        ):
            raise ValueError(
                f"Enemy shield '{item_id}' must provide a defense bonus."
            )

    for item_id in dict.fromkeys(armor_ids):
        armor = item(item_id)
        if (
            armor.item_type is not ItemType.ARMOR
            or armor.defense_bonus > 0
        ):
            raise ValueError(
                f"Enemy armor '{item_id}' must be body armor, not a shield."
            )
        if (
            template.armor_reduction_filter is not None
            and armor.protection != template.armor_reduction_filter
        ):
            raise ValueError(
                f"Enemy armor '{item_id}' protection "
                f"{armor.protection} does not match the selected "
                f"damage reduction {template.armor_reduction_filter}."
            )

    one_handed = [
        item_id
        for item_id in melee_ids
        if item(item_id).grip is WeaponGrip.ONE_HANDED
    ]
    two_handed = [
        item_id
        for item_id in melee_ids
        if item(item_id).grip is WeaponGrip.TWO_HANDED
    ]
    for loadout in template.melee_loadouts:
        if loadout == "one_handed" and not one_handed:
            raise ValueError(
                "One-handed loadout requires a one-handed melee weapon."
            )
        if loadout == "shield" and (not one_handed or not shield_ids):
            raise ValueError(
                "Shield loadout requires a one-handed melee weapon and shield."
            )
        if (
            loadout == "dual_wield"
            and (not one_handed or not second_weapon_ids)
        ):
            raise ValueError(
                "Dual-wield loadout requires one-handed main and second weapons."
            )
        if loadout == "two_handed" and not two_handed:
            raise ValueError(
                "Two-handed loadout requires a two-handed melee weapon."
            )
        if loadout == "natural" and not template.natural_attacks:
            raise ValueError(
                "Natural loadout requires at least one natural attack."
            )

    race_pool = template.allowed_races or (template.race,)
    if any(not race.strip() for race in race_pool):
        raise ValueError("Enemy allowed races must be non-empty.")


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
