"""Generic world entity operations."""

from __future__ import annotations

from ..models import EntityKind, WorldEntity


def create_entity(
    service,
    entity_id: str,
    room_id: str,
    kind: EntityKind,
    name: str,
    description: str | None = None,
) -> WorldEntity:
    return service.database.create_world_entity(
        entity_id, room_id, kind, name, description
    )


def move_entity(service, entity_id: str, room_id: str) -> WorldEntity:
    return service.database.move_world_entity(entity_id, room_id)


def remove_entity(service, entity_id: str) -> None:
    service.database.remove_world_entity(entity_id)


class WorldEntityMixin:
    create_entity = create_entity
    move_entity = move_entity
    remove_entity = remove_entity
