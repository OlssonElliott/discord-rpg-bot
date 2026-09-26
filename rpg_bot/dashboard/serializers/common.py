"""Serialization helpers for the local DM dashboard API."""

from dataclasses import asdict
from typing import Any
from urllib.parse import quote

from ...world.enemies import EnemyInstance, EnemyTemplate
from ...inventory import ItemTemplate, ItemType
from ...characters.models import CharacterCombatStatus
from ...media.portraits import CharacterPortraitStore
from ...media.room_images import RoomImageStore
from ...world import AreaGraph, Room, RoomEditorNode
from ...world.service import WorldService


JsonObject = dict[str, Any]


def _stack_data(stack: object) -> JsonObject:
    return {
        "id": stack.item.id,
        "name": stack.item.name,
        "description": stack.item.description,
        "quantity": stack.quantity,
    }


def _template_data(template: ItemTemplate) -> JsonObject:
    data: JsonObject = {
        "id": template.template_id,
        "item_type": template.item_type.value,
        "name": template.name,
        "rarity": template.rarity,
        "value": template.value,
        "description": template.description,
        "weight": template.weight,
        "slot_cost": template.slot_cost,
        "stackable": template.stackable,
        "content": template.content,
    }
    if template.item_type is ItemType.WEAPON:
        data.update(
            grip=template.grip.value if template.grip else "one_handed",
            durability=template.durability,
            damage=template.damage_parts[0].amount if template.damage_parts else 1,
            damage_type=(
                template.damage_parts[0].damage_type
                if template.damage_parts
                else "physical"
            ),
        )
    elif template.item_type is ItemType.ARMOR:
        data.update(
            protection=template.protection,
            dodge_penalty=template.dodge_penalty,
            strength_requirement=template.strength_requirement,
        )
    elif template.item_type is ItemType.CONTAINER:
        data.update(capacity=template.capacity, can_equip=template.can_equip)
    elif template.item_type is ItemType.CONSUMABLE:
        data["affected_stat"] = template.affected_stat
        data["affected_amount"] = template.affected_amount
    return data


def _container_template_data(template: object) -> JsonObject:
    return {
        "id": template.template_id,
        "name": template.name,
        "type": template.container_type.value,
        "description": template.description or "",
        "default_has_lock": template.default_has_lock,
        "default_is_locked": template.default_is_locked,
        "default_is_broken": template.default_is_broken,
        "default_unlock_difficulty": template.default_unlock_difficulty,
        "default_hidden": template.default_hidden,
        "default_discovery_difficulty": template.default_discovery_difficulty,
    }


def _room_feature_data(feature: object) -> JsonObject:
    return {
        "id": feature.id,
        "room_id": feature.room_id,
        "name": feature.name,
        "description": feature.description or "",
        "feature_type": feature.feature_type.value,
    }


def _room_feature_template_data(template: object) -> JsonObject:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description or "",
        "feature_type": template.feature_type.value,
    }


def _container_data(container: object, contents: tuple[object, ...]) -> JsonObject:
    item_data = [_stack_data(stack) for stack in contents]
    return {
        "id": container.id,
        "room_id": container.room_id,
        "template_id": container.template_id,
        "name": container.name,
        "type": container.container_type.value,
        "description": container.description or "",
        "has_lock": container.has_lock,
        "is_locked": container.is_locked,
        "is_broken": container.is_broken,
        "unlock_difficulty": container.unlock_difficulty,
        "hidden": container.hidden,
        "discovery_difficulty": container.discovery_difficulty,
        "is_open": container.is_open,
        "searched": container.searched,
        "item_count": sum(item["quantity"] for item in item_data),
        "contents": item_data,
    }


def _enemy_template_data(template: EnemyTemplate) -> JsonObject:
    return {
        "id": template.template_id,
        "name": template.name,
        "description": template.description or "",
        "race": template.race,
        "difficulty_level": template.difficulty_level,
        "strength": template.strength,
        "dexterity": template.dexterity,
        "arcana": template.arcana,
        "vitality": template.vitality,
        "insight": template.insight,
        "personality": template.personality,
        "max_hp": template.max_hp,
        "armor": template.armor,
        "magical_resistance": template.magical_resistance,
        "attack_dc": template.attack_dc,
        "defense_dc": template.defense_dc,
        "damage": template.damage,
        "attack_profile": template.attack_profile,
        "special_ability": template.special_ability,
        "typical_behaviour": template.typical_behaviour,
        "main_hand_item_id": template.main_hand_item_id,
        "off_hand_item_id": template.off_hand_item_id,
        "armor_item_id": template.armor_item_id,
    }


def _enemy_data(
    enemy: EnemyInstance,
    template: EnemyTemplate,
) -> JsonObject:
    return {
        "id": enemy.id,
        "room_id": enemy.room_id,
        "template_id": enemy.template_id,
        "template_name": template.name,
        "name": enemy.name,
        "description": enemy.description or "",
        "current_hp": enemy.current_hp,
        "max_hp": template.max_hp,
        "status": enemy.status.value,
    }


def _legacy_enemy_data(entity: object) -> JsonObject:
    return {
        "id": entity.id,
        "room_id": entity.room_id,
        "template_id": None,
        "template_name": None,
        "name": entity.name,
        "description": entity.description or "",
        "current_hp": None,
        "max_hp": None,
        "status": "active",
    }


def _room_image_data(
    room: Room,
    room_images: RoomImageStore,
) -> JsonObject:
    path = room_images.path_for(room.scene_image_path)
    return {
        "id": room.id,
        "room_image_url": (
            f"/api/rooms/{quote(room.id, safe='')}/image"
            f"?version={quote(path.stem, safe='')}"
            if path is not None
            else room.scene_image_url
        ),
    }


def _node_data(node: RoomEditorNode, room_images: RoomImageStore) -> JsonObject:
    room = node.room
    stored_image = room_images.path_for(room.scene_image_path)
    if stored_image is not None:
        image_version = stored_image.stem
        room_image_url = (
            f"/api/rooms/{quote(room.id, safe='')}/image"
            f"?version={quote(image_version, safe='')}"
        )
    else:
        room_image_url = room.scene_image_url
    return {
        "id": room.id,
        "area_id": room.area_id,
        "name": room.name,
        "description": room.description or "",
        "room_image_url": room_image_url,
        "position": {"x": node.x, "y": node.y},
        "counts": {
            "players": len(room.characters),
            "enemies": len(room.enemies),
            "items": sum(stack.quantity for stack in room.loose_items),
            "containers": len(room.containers),
        },
        "players": [
            {"id": character.character_id, "name": character.name}
            for character in room.characters
        ],
        "enemies": [asdict(entity) for entity in room.enemies],
        "npcs": [asdict(entity) for entity in room.npcs],
        "containers": [asdict(entity) for entity in room.containers],
        "loose_items": [_stack_data(stack) for stack in room.loose_items],
    }


def _graph_data(graph: AreaGraph, room_images: RoomImageStore) -> JsonObject:
    return {
        "area": {
            "id": graph.area.id,
            "name": graph.area.name,
            "description": graph.area.description or "",
        },
        "nodes": [_node_data(node, room_images) for node in graph.nodes],
        "connections": [asdict(connection) for connection in graph.connections],
    }


def _character_portrait_url(
    character: object,
    portraits: CharacterPortraitStore,
) -> str | None:
    if character.character_id is None:
        return None
    if portraits.path_for(character.portrait_key) is None:
        return None
    version = quote(character.portrait_key or "portrait", safe="")
    return (
        f"/api/characters/{character.character_id}/portrait"
        f"?version={version}"
    )


def _character_data(
    world: WorldService,
    portraits: CharacterPortraitStore,
    character: object,
) -> JsonObject:
    state = world.database.get_character_combat_state(character.character_id)
    room = (
        world.get_room(character.current_room_id)
        if character.current_room_id is not None
        else None
    )
    return {
        "id": character.character_id,
        "discord_user_id": character.discord_user_id,
        "name": character.name,
        "current_room_id": character.current_room_id,
        "current_room_name": room.name if room is not None else None,
        "is_active": character.is_active,
        "portrait_url": _character_portrait_url(character, portraits),
        "race": character.race,
        "lineage": character.lineage,
        "hp": character.hp,
        "max_hp": character.max_hp,
        "hunger": character.hunger,
        "status": state.status.value,
    }


def _catalog_item_summary(
    world: WorldService,
    template_id: str,
) -> JsonObject:
    try:
        template = world.catalog.get(template_id)
    except ValueError:
        return {
            "template_id": template_id,
            "name": template_id,
            "description": "",
        }
    return {
        "template_id": template.template_id,
        "name": template.name,
        "description": template.description,
    }


def _character_admin_data(
    world: WorldService,
    portraits: CharacterPortraitStore,
    character: object,
) -> JsonObject:
    character_id = character.character_id
    if character_id is None:
        raise ValueError("The character has not been saved.")

    inventory = world.database.get_character_inventory(character_id)
    equipped_slots = {
        instance_id: slot.value
        for slot, instance_id in inventory.equipment.items()
    }
    inventory_data: list[JsonObject] = []
    for item in inventory.items:
        summary = _catalog_item_summary(world, item.template_id)
        inventory_data.append(
            {
                "id": item.instance_id,
                **summary,
                "quantity": item.quantity,
                "durability": item.durability,
                "equipped_slot": equipped_slots.get(item.instance_id),
            }
        )

    equipment_data: list[JsonObject] = []
    for slot, instance_id in inventory.equipment.items():
        item = next(
            (
                candidate
                for candidate in inventory.items
                if candidate.instance_id == instance_id
            ),
            None,
        )
        summary = (
            _catalog_item_summary(world, item.template_id)
            if item is not None
            else {
                "template_id": instance_id,
                "name": instance_id,
                "description": "",
            }
        )
        equipment_data.append(
            {
                "slot": slot.value,
                "id": instance_id,
                **summary,
            }
        )

    combat_state = world.database.get_character_combat_state(character_id)
    room = (
        world.get_room(character.current_room_id)
        if character.current_room_id is not None
        else None
    )
    death_save_dc = (
        10 + (abs(character.hp) + 1) // 2
        if combat_state.status is CharacterCombatStatus.DOWNED
        else None
    )
    return {
        "kind": "character",
        "source_id": str(character_id),
        "id": character_id,
        "discord_user_id": character.discord_user_id,
        "name": character.name,
        "description": "",
        "portrait_url": _character_portrait_url(character, portraits),
        "hp": character.hp,
        "max_hp": character.max_hp,
        "hunger": character.hunger,
        "status": combat_state.status.value,
        "failed_death_saves": combat_state.failed_death_saves,
        "death_save_dc": death_save_dc,
        "stance": character.stance.value,
        "race": character.race,
        "lineage": character.lineage,
        "age": character.age,
        "gender": character.gender,
        "current_room_id": character.current_room_id,
        "current_room_name": room.name if room is not None else None,
        "is_active": character.is_active,
        "attributes": dict(character.attributes),
        "skills": dict(character.skills),
        "inventory": inventory_data,
        "equipment": equipment_data,
        "wallet": {
            "copper": inventory.copper,
            "silver": inventory.silver,
            "gold": inventory.gold,
        },
        "enemy": None,
    }
