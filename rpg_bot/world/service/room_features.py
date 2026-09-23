"""Room feature instance and template operations."""

from __future__ import annotations

from ..models import NotFoundError
from ..room_features import RoomFeature, RoomFeatureTemplate, RoomFeatureType


def create_room_feature(
    service,
    room_id: str,
    feature_id: str,
    name: str,
    feature_type: str,
    description: str | None = None,
):
    try:
        parsed_type = RoomFeatureType(feature_type)
    except ValueError as error:
        raise ValueError(
            f"Unknown room feature type '{feature_type}'."
        ) from error
    return service.database.create_room_feature(
        feature_id,
        room_id,
        name,
        parsed_type,
        description,
    )


def get_room_feature(service, feature_id: str):
    return service.database.get_room_feature(feature_id)


def list_room_features(service, room_id: str):
    return service.database.list_room_features(room_id)


def update_room_feature(
    service,
    feature_id: str,
    *,
    name: str,
    description: str | None,
    feature_type: str,
):
    current = service.database.get_room_feature(feature_id)
    if current is None:
        raise NotFoundError(
            f"Room feature '{feature_id}' does not exist."
        )
    try:
        parsed_type = RoomFeatureType(feature_type)
    except ValueError as error:
        raise ValueError(
            f"Unknown room feature type '{feature_type}'."
        ) from error
    return service.database.update_room_feature(
        RoomFeature(
            current.id,
            current.room_id,
            name,
            parsed_type,
            description,
        )
    )


def remove_room_feature(service, feature_id: str) -> None:
    service.database.remove_room_feature(feature_id)


def create_room_feature_template(
    service,
    template_id: str,
    name: str,
    feature_type: str,
    description: str | None = None,
):
    try:
        parsed_type = RoomFeatureType(feature_type)
    except ValueError as error:
        raise ValueError(
            f"Unknown room feature type '{feature_type}'."
        ) from error
    return service.database.create_room_feature_template(
        template_id,
        name,
        parsed_type,
        description,
    )


def get_room_feature_template(service, template_id: str):
    return service.database.get_room_feature_template(template_id)


def list_room_feature_templates(service):
    return service.database.list_room_feature_templates()


def update_room_feature_template(
    service,
    template_id: str,
    *,
    name: str,
    description: str | None,
    feature_type: str,
):
    current = service.database.get_room_feature_template(template_id)
    if current is None:
        raise NotFoundError(
            f"Room feature template '{template_id}' does not exist."
        )
    try:
        parsed_type = RoomFeatureType(feature_type)
    except ValueError as error:
        raise ValueError(
            f"Unknown room feature type '{feature_type}'."
        ) from error
    return service.database.update_room_feature_template(
        RoomFeatureTemplate(
            current.id,
            name,
            parsed_type,
            description,
        )
    )


def remove_room_feature_template(service, template_id: str) -> None:
    service.database.remove_room_feature_template(template_id)


class WorldRoomFeatureMixin:
    create_room_feature = create_room_feature
    get_room_feature = get_room_feature
    list_room_features = list_room_features
    update_room_feature = update_room_feature
    remove_room_feature = remove_room_feature
    create_room_feature_template = create_room_feature_template
    get_room_feature_template = get_room_feature_template
    list_room_feature_templates = list_room_feature_templates
    update_room_feature_template = update_room_feature_template
    remove_room_feature_template = remove_room_feature_template
