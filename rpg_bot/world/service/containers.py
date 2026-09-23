"""Container template, instance, and discovery operations."""

from __future__ import annotations

from ..containers import ContainerInstance, ContainerTemplate, ContainerType
from ..models import NotFoundError


def list_container_templates(service):
    return service.database.list_container_templates()


def get_container_template(service, template_id: str):
    return service.database.get_container_template(template_id)


def create_container_template(
    service,
    template_id: str,
    name: str,
    container_type: str,
    description: str | None = None,
    *,
    default_has_lock: bool = False,
    default_is_locked: bool = False,
    default_is_broken: bool = False,
    default_unlock_difficulty: int | None = None,
    default_hidden: bool = False,
    default_discovery_difficulty: int | None = None,
):
    try:
        parsed_type = ContainerType(container_type)
    except ValueError as error:
        raise ValueError(f"Unknown container type '{container_type}'.") from error
    return service.database.create_container_template(
        ContainerTemplate(
            template_id,
            name,
            parsed_type,
            description,
            default_has_lock,
            default_is_locked,
            default_is_broken,
            default_unlock_difficulty,
            default_hidden,
            default_discovery_difficulty,
        )
    )


def update_container_template(
    service,
    template_id: str,
    name: str,
    container_type: str,
    description: str | None = None,
    *,
    default_has_lock: bool = False,
    default_is_locked: bool = False,
    default_is_broken: bool = False,
    default_unlock_difficulty: int | None = None,
    default_hidden: bool = False,
    default_discovery_difficulty: int | None = None,
):
    try:
        parsed_type = ContainerType(container_type)
    except ValueError as error:
        raise ValueError(f"Unknown container type '{container_type}'.") from error
    return service.database.update_container_template(
        template_id,
        ContainerTemplate(
            template_id,
            name,
            parsed_type,
            description,
            default_has_lock,
            default_is_locked,
            default_is_broken,
            default_unlock_difficulty,
            default_hidden,
            default_discovery_difficulty,
        ),
    )


def place_container(
    service,
    room_id: str,
    template_id: str,
    *,
    instance_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    has_lock: bool | None = None,
    is_locked: bool | None = None,
    is_broken: bool | None = None,
    unlock_difficulty: int | None = None,
    hidden: bool | None = None,
    discovery_difficulty: int | None = None,
    is_open: bool = False,
    searched: bool = False,
):
    return service.database.create_container_instance(
        room_id,
        template_id,
        instance_id=instance_id,
        name=name,
        description=description,
        has_lock=has_lock,
        is_locked=is_locked,
        is_broken=is_broken,
        unlock_difficulty=unlock_difficulty,
        hidden=hidden,
        discovery_difficulty=discovery_difficulty,
        is_open=is_open,
        searched=searched,
    )


def get_container(service, container_id: str):
    return service.database.get_container_instance(container_id)


def list_room_containers(service, room_id: str):
    return service.database.list_room_container_instances(room_id)


def update_container(
    service,
    container_id: str,
    *,
    name: str,
    description: str | None,
    has_lock: bool,
    is_locked: bool,
    is_broken: bool,
    unlock_difficulty: int | None,
    hidden: bool,
    discovery_difficulty: int | None,
    is_open: bool,
    searched: bool,
):
    current = service.database.get_container_instance(container_id)
    if current is None:
        raise NotFoundError(f"Container '{container_id}' does not exist.")
    return service.database.update_container_instance(
        ContainerInstance(
            current.id,
            current.room_id,
            current.template_id,
            name,
            current.container_type,
            description,
            has_lock,
            is_locked,
            is_broken,
            unlock_difficulty,
            hidden,
            discovery_difficulty,
            is_open,
            searched,
        )
    )


def remove_container(service, container_id: str) -> None:
    service.database.remove_container_instance(container_id)


def character_knows_container(
    service,
    character_id: int,
    container_id: str,
) -> bool:
    return service.database.character_knows_container(character_id, container_id)


def mark_container_discovered(
    service,
    character_id: int,
    container_id: str,
) -> None:
    service.database.mark_container_discovered(character_id, container_id)

class WorldContainerMixin:
    list_container_templates = list_container_templates
    get_container_template = get_container_template
    create_container_template = create_container_template
    update_container_template = update_container_template
    place_container = place_container
    get_container = get_container
    list_room_containers = list_room_containers
    update_container = update_container
    remove_container = remove_container
    character_knows_container = character_knows_container
    mark_container_discovered = mark_container_discovered


