"""Enemy template and instance operations for the world service."""

from __future__ import annotations

from ...inventory import ItemType
from ..enemies import EnemyInstance, EnemyStatus, EnemyTemplate
from ..models import InventoryHolder, NotFoundError


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
) -> EnemyInstance:
    template = service.database.get_enemy_template(template_id)
    if template is None:
        raise NotFoundError(
            f"Enemy template '{template_id}' does not exist."
        )

    service._validate_enemy_equipment_template(template)
    enemy = service.database.create_enemy_instance(
        room_id,
        template_id,
        instance_id=instance_id,
        name=name,
        description=description,
    )

    try:
        equipment_ids = dict.fromkeys(
            item_id
            for item_id in (
                template.main_hand_item_id,
                template.off_hand_item_id,
                template.armor_item_id,
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
        )
    )


def validate_enemy_equipment_template(
    service,
    template: EnemyTemplate,
) -> None:
    equipment = (
        (
            "main hand",
            template.main_hand_item_id,
            ItemType.WEAPON,
        ),
        (
            "off hand",
            template.off_hand_item_id,
            ItemType.WEAPON,
        ),
        (
            "armor",
            template.armor_item_id,
            ItemType.ARMOR,
        ),
    )

    for label, item_id, expected_type in equipment:
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
