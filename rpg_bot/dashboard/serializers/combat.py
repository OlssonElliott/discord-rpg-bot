"""Combat serialization helpers for the local DM dashboard API."""

from typing import Any

from ...combat import AttackResult, CombatScene, EnemyAttackResult
from ...inventory import ItemType
from ...world import InventoryHolder
from ...world.service import WorldService
from .common import _catalog_item_summary


JsonObject = dict[str, Any]


def _combatant_usable_items_data(
    world: WorldService,
    kind: str,
    source_id: str,
) -> list[JsonObject]:
    usable: list[JsonObject] = []

    if kind == "character":
        try:
            character_id = int(source_id)
        except ValueError:
            return []
        inventory = world.database.get_character_inventory(character_id)
        candidates = (
            (item.instance_id, item.template_id, item.quantity)
            for item in inventory.items
        )
        supported_stats = {"hp", "hunger"}
    elif kind == "enemy":
        enemy = world.get_enemy(source_id)
        if enemy is None:
            return []
        candidates = (
            (stack.item.id, stack.item.id, stack.quantity)
            for stack in world.inventory(InventoryHolder.entity(enemy.id))
        )
        # Enemies do not currently have Hunger, so only HP consumables are
        # combat-usable for them. Other carried items remain loot/inventory.
        supported_stats = {"hp"}
    else:
        return []

    for item_id, template_id, quantity in candidates:
        try:
            template = world.catalog.get(template_id)
        except ValueError:
            continue
        if (
            template.item_type is not ItemType.CONSUMABLE
            or template.affected_stat not in supported_stats
            or template.affected_amount is None
        ):
            continue
        usable.append(
            {
                "id": item_id,
                "template_id": template.template_id,
                "name": template.name,
                "quantity": quantity,
                "affected_stat": template.affected_stat,
                "affected_amount": template.affected_amount,
            }
        )
    return usable


def _combatant_vitals_data(
    world: WorldService,
    kind: str,
    source_id: str,
) -> JsonObject:
    if kind == "enemy":
        enemy = world.get_enemy(source_id)
        if enemy is None:
            return {
                "hp": None,
                "max_hp": None,
                "hunger": None,
                "character_status": None,
                "failed_death_saves": None,
                "death_save_dc": None,
            }
        template = world.get_enemy_template(enemy.template_id)
        return {
            "hp": enemy.current_hp,
            "max_hp": template.max_hp if template is not None else None,
            "hunger": None,
            "character_status": None,
            "failed_death_saves": None,
            "death_save_dc": None,
        }
    if kind != "character":
        return {
            "hp": None,
            "max_hp": None,
            "hunger": None,
            "character_status": None,
            "failed_death_saves": None,
            "death_save_dc": None,
        }
    try:
        character_id = int(source_id)
    except ValueError:
        return {
            "hp": None,
            "max_hp": None,
            "hunger": None,
            "character_status": None,
            "failed_death_saves": None,
            "death_save_dc": None,
        }
    character = next(
        (
            candidate
            for candidate in world.list_characters()
            if candidate.character_id == character_id
        ),
        None,
    )
    if character is None:
        return {
            "hp": None,
            "max_hp": None,
            "hunger": None,
            "character_status": None,
            "failed_death_saves": None,
            "death_save_dc": None,
        }
    state = world.database.get_character_combat_state(character_id)
    death_save_dc = (
        10 + (abs(character.hp) + 1) // 2
        if state.status.value == "downed"
        else None
    )
    return {
        "hp": character.hp,
        "max_hp": character.max_hp,
        "hunger": character.hunger,
        "character_status": state.status.value,
        "failed_death_saves": state.failed_death_saves,
        "death_save_dc": death_save_dc,
    }


def _combat_scene_data(scene: CombatScene, world: WorldService) -> JsonObject:
    room = world.get_room(scene.room_id)
    return {
        "id": scene.id,
        "guild_id": scene.guild_id,
        "room_id": scene.room_id,
        "room_name": room.name if room is not None else scene.room_id,
        "area_id": room.area_id if room is not None else None,
        "status": scene.status.value,
        "round_number": scene.round_number,
        "current_turn_kind": (
            scene.current_turn_kind.value
            if scene.current_turn_kind is not None
            else None
        ),
        "current_turn_source_id": scene.current_turn_source_id,
        "landmarks": [
            {
                "id": landmark.id,
                "name": landmark.name,
                "description": landmark.description or "",
                "source_feature_id": landmark.source_feature_id,
                "source_connection_id": landmark.source_connection_id,
                "feature_type": landmark.feature_type,
                "synthetic": landmark.synthetic,
                "cover": landmark.cover.value,
                "x": landmark.x,
                "y": landmark.y,
            }
            for landmark in scene.landmarks
        ],
        "routes": [
            {
                "source_landmark_id": route.source_landmark_id,
                "destination_landmark_id": route.destination_landmark_id,
                "distance": route.distance.value,
                "movement_cost": route.movement_cost,
                "terrain": route.terrain.value,
                "base_blocked": route.base_blocked,
                "blocked": route.blocked,
                "automatic": route.automatic,
                "effects": [
                    {
                        "id": effect.id,
                        "name": effect.name,
                        "effect_type": effect.effect_type,
                        "blocks_movement": effect.blocks_movement,
                        "movement_cost_modifier": effect.movement_cost_modifier,
                        "remaining_rounds": effect.remaining_rounds,
                    }
                    for effect in route.effects
                ],
            }
            for route in scene.routes
        ],
        "combatants": [
            {
                "kind": combatant.kind.value,
                "source_id": combatant.source_id,
                "name": combatant.name,
                "landmark_id": combatant.landmark_id,
                "relation": combatant.relation.value,
                "initiative_roll": combatant.initiative_roll,
                "initiative_score": combatant.initiative_score,
                "acted_this_round": combatant.acted_this_round,
                "movement_budget": combatant.movement_budget,
                "movement_remaining": combatant.movement_remaining,
                "route_source_landmark_id": combatant.route_source_landmark_id,
                "route_destination_landmark_id": combatant.route_destination_landmark_id,
                "route_progress": combatant.route_progress,
                "route_cost": combatant.route_cost,
                "is_between_landmarks": combatant.is_between_landmarks,
                "standard_action_spent": combatant.standard_action_spent,
                "defending": combatant.defending,
                "dashed": combatant.dashed,
                "usable_items": _combatant_usable_items_data(
                    world,
                    combatant.kind.value,
                    combatant.source_id,
                ),
                **_combatant_vitals_data(
                    world,
                    combatant.kind.value,
                    combatant.source_id,
                ),
                "is_current_turn": (
                    combatant.kind is scene.current_turn_kind
                    and combatant.source_id == scene.current_turn_source_id
                ),
            }
            for combatant in scene.combatants
        ],
        "log_entries": [
            {
                "id": entry.id,
                "round_number": entry.round_number,
                "event_type": entry.event_type,
                "message": entry.message,
                "created_at": entry.created_at,
                "actor_kind": (
                    entry.actor_kind.value
                    if entry.actor_kind is not None
                    else None
                ),
                "actor_source_id": entry.actor_source_id,
                "actor_name": entry.actor_name,
            }
            for entry in scene.log_entries
        ],
    }


def _combat_state_data(
    scene: CombatScene | None,
    world: WorldService,
) -> JsonObject:
    return {
        "scene": _combat_scene_data(scene, world) if scene is not None else None
    }


def _attack_result_data(result: AttackResult) -> JsonObject:
    return {
        "attacker_kind": result.attacker_kind.value,
        "attacker_source_id": result.attacker_source_id,
        "attacker_name": result.attacker_name,
        "target_kind": result.target_kind.value,
        "target_source_id": result.target_source_id,
        "target_name": result.target_name,
        "weapon_name": result.weapon_name,
        "attack_attribute": result.attack_attribute,
        "attack_roll": result.attack_roll,
        "attack_modifier": result.attack_modifier,
        "attack_total": result.attack_total,
        "defense_dc": result.defense_dc,
        "hit": result.hit,
        "critical": result.critical,
        "damage_rolls": [
            {
                "die": part.die,
                "damage_type": part.damage_type,
                "roll": part.roll,
            }
            for part in result.damage_rolls
        ],
        "raw_damage": result.raw_damage,
        "reduction": result.reduction,
        "reduction_type": result.reduction_type,
        "final_damage": result.final_damage,
        "target_hp": result.target_hp,
        "target_max_hp": result.target_max_hp,
        "target_defeated": result.target_defeated,
    }


def _enemy_attack_result_data(result: EnemyAttackResult) -> JsonObject:
    return {
        "attacker_source_id": result.attacker_source_id,
        "attacker_name": result.attacker_name,
        "target_source_id": result.target_source_id,
        "target_name": result.target_name,
        "attack_profile": result.attack_profile,
        "attack_dc": result.attack_dc,
        "defense_method": result.defense_method,
        "defense_attribute": result.defense_attribute,
        "defense_roll": result.defense_roll,
        "defense_modifier": result.defense_modifier,
        "defense_total": result.defense_total,
        "defended": result.defended,
        "critical_defense": result.critical_defense,
        "damage_expression": result.damage_expression,
        "damage_rolls": list(result.damage_rolls),
        "raw_damage": result.raw_damage,
        "armor_reduction": result.armor_reduction,
        "final_damage": result.final_damage,
        "target_hp": result.target_hp,
        "target_max_hp": result.target_max_hp,
        "target_down": result.target_down,
        "target_status": result.target_status,
        "target_dead": result.target_dead,
    }


def _combatant_inspect_data(
    world: WorldService,
    kind: str,
    source_id: str,
    room_id: str,
) -> JsonObject | None:
    if kind == "character":
        try:
            character_id = int(source_id)
        except ValueError:
            return None
        character = next(
            (
                candidate
                for candidate in world.list_characters()
                if candidate.character_id == character_id
            ),
            None,
        )
        if character is None:
            return None

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

        equipment_data = []
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

        combat_state = world.database.get_character_combat_state(
            character_id
        )
        death_save_dc = (
            10 + (abs(character.hp) + 1) // 2
            if combat_state.status.value == "downed"
            else None
        )
        return {
            "kind": "character",
            "source_id": source_id,
            "name": character.name,
            "description": "",
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

    if kind == "enemy":
        enemy = world.get_enemy(source_id)
        if enemy is not None:
            template = world.get_enemy_template(enemy.template_id)
            if template is None:
                return None

            equipment_templates = {
                item_id: slot
                for slot, item_id in (
                    ("main_hand", template.main_hand_item_id),
                    ("off_hand", template.off_hand_item_id),
                    ("armor", template.armor_item_id),
                )
                if item_id is not None
            }
            inventory_data = [
                {
                    "id": stack.item.id,
                    "template_id": stack.item.id,
                    "name": stack.item.name,
                    "description": stack.item.description or "",
                    "quantity": stack.quantity,
                    "durability": None,
                    "equipped_slot": equipment_templates.get(stack.item.id),
                }
                for stack in world.inventory(
                    InventoryHolder.entity(enemy.id)
                )
            ]
            equipment_data = [
                {
                    "slot": slot,
                    "id": item_id,
                    **_catalog_item_summary(world, item_id),
                }
                for slot, item_id in (
                    ("main_hand", template.main_hand_item_id),
                    ("off_hand", template.off_hand_item_id),
                    ("armor", template.armor_item_id),
                )
                if item_id is not None
            ]
            return {
                "kind": "enemy",
                "source_id": source_id,
                "name": enemy.name,
                "description": (
                    enemy.description or template.description or ""
                ),
                "hp": enemy.current_hp,
                "max_hp": template.max_hp,
                "hunger": None,
                "status": enemy.status.value,
                "failed_death_saves": None,
                "death_save_dc": None,
                "stance": None,
                "race": template.race,
                "lineage": None,
                "age": None,
                "gender": None,
                "attributes": {
                    "strength": template.strength,
                    "dexterity": template.dexterity,
                    "arcana": template.arcana,
                    "vitality": template.vitality,
                    "insight": template.insight,
                    "personality": template.personality,
                },
                "skills": {},
                "inventory": inventory_data,
                "equipment": equipment_data,
                "wallet": None,
                "enemy": {
                    "template_id": template.template_id,
                    "template_name": template.name,
                    "difficulty_level": template.difficulty_level,
                    "armor": template.armor,
                    "magical_resistance": template.magical_resistance,
                    "attack_dc": template.attack_dc,
                    "defense_dc": template.defense_dc,
                    "damage": template.damage,
                    "attack_profile": template.attack_profile,
                    "special_ability": template.special_ability,
                    "typical_behaviour": template.typical_behaviour,
                },
            }

        room = world.get_room(room_id)
        legacy = next(
            (
                candidate
                for candidate in room.enemies
                if candidate.id == source_id
            ),
            None,
        ) if room is not None else None
        if legacy is None:
            return None
        return {
            "kind": "enemy",
            "source_id": source_id,
            "name": legacy.name,
            "description": legacy.description or "",
            "hp": None,
            "max_hp": None,
            "hunger": None,
            "status": "active",
            "failed_death_saves": None,
            "death_save_dc": None,
            "stance": None,
            "race": None,
            "lineage": None,
            "age": None,
            "gender": None,
            "attributes": {},
            "skills": {},
            "inventory": [],
            "equipment": [],
            "wallet": None,
            "enemy": None,
        }

    return None

