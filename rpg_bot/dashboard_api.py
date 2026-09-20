"""Framework-neutral JSON API for the local DM dashboard."""

from dataclasses import asdict
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from .combat import AttackResult, CombatScene, EnemyAttackResult
from .combat_service import CombatService
from .dungeon import ConnectionType, TrapDamageType, TrapState
from .enemies import EnemyInstance, EnemyTemplate
from .inventory import ItemTemplate, ItemType, WeaponGrip
from .room_images import InvalidRoomImageError, RoomImageStore
from .world import (
    AreaGraph,
    EntityKind,
    InventoryHolder,
    Room,
    RoomEditorNode,
    WorldError,
)
from .world_service import WorldService


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def _stack_data(stack: object) -> JsonObject:
    return {
        "id": stack.item.id,
        "name": stack.item.name,
        "description": stack.item.description,
        "quantity": stack.quantity,
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


def _character_data(character: object) -> JsonObject:
    return {
        "id": character.character_id,
        "discord_user_id": character.discord_user_id,
        "name": character.name,
        "current_room_id": character.current_room_id,
        "is_active": character.is_active,
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
                "obstacle": route.obstacle,
                "blocked": route.blocked,
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


def _enemy_template_data(
    template: EnemyTemplate,
) -> JsonObject:
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

        return {
            "kind": "character",
            "source_id": source_id,
            "name": character.name,
            "description": "",
            "hp": character.hp,
            "max_hp": character.max_hp,
            "status": "active" if character.hp > 0 else "down",
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
                "status": enemy.status.value,
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
            "status": "active",
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


class DashboardAPI:
    """Translate HTTP-shaped requests into deterministic service calls."""

    def __init__(
        self,
        world: WorldService,
        room_images: RoomImageStore | None = None,
        *,
        combat: CombatService | None = None,
        guild_id: int | None = None,
    ) -> None:
        self.world = world
        self.room_images = room_images or RoomImageStore()
        self.combat = combat or CombatService(world.database)
        self.guild_id = guild_id
        self._connection_trap_damage: dict[tuple[str, str], int] = {}

    def upload_room_image(
        self,
        room_id: str,
        content: bytes,
        content_type: str,
        original_filename: str | None = None,
    ) -> ApiResponse:
        """Validate, persist, and atomically associate a room image."""
        room = self.world.get_room(room_id)
        if room is None:
            return 404, {"error": f"Room '{room_id}' does not exist."}
        try:
            new_key = self.room_images.save(
                content, content_type, original_filename
            )
            try:
                updated = self.world.set_room_scene_image(room_id, new_key)
            except Exception:
                self.room_images.remove(new_key)
                raise
            self.room_images.remove(room.scene_image_path)
            return 200, self._room_image_data(updated)
        except (InvalidRoomImageError, ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def room_image_path(self, room_id: str) -> Path | None:
        room = self.world.get_room(room_id)
        if room is None:
            return None
        return self.room_images.path_for(room.scene_image_path)

    def handle(
        self,
        method: str,
        path: str,
        body: JsonObject | None = None,
    ) -> ApiResponse:
        body = body or {}
        try:
            return self._handle(method.upper(), path.rstrip("/") or "/", body)
        except (ValueError, WorldError) as error:
            return 400, {"error": str(error)}

    def _handle(self, method: str, path: str, body: JsonObject) -> ApiResponse:
        if path == "/api/combat":
            guild_id = self._combat_guild_id()
            if method == "GET":
                return 200, _combat_state_data(
                    self.combat.current(guild_id),
                    self.world,
                )
            if method == "POST":
                scene = self.combat.start(
                    guild_id,
                    self._text(body, "room_id"),
                )
                return 201, _combat_state_data(scene, self.world)
            if method == "DELETE":
                self.combat.end(guild_id)
                return 200, _combat_state_data(None, self.world)

        if path == "/api/combat/landmarks" and method == "POST":
            scene = self.combat.add_landmark(
                self._combat_guild_id(),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 201, _combat_state_data(scene, self.world)

        match = re.fullmatch(r"/api/combat/landmarks/([^/]+)", path)
        if match and method == "PATCH":
            scene = self.combat.set_landmark_position(
                self._combat_guild_id(),
                match.group(1),
                self._number(body, "x"),
                self._number(body, "y"),
            )
            return 200, _combat_state_data(scene, self.world)
        if match and method == "DELETE":
            scene = self.combat.remove_landmark(
                self._combat_guild_id(),
                match.group(1),
            )
            return 200, _combat_state_data(scene, self.world)

        if path == "/api/combat/routes" and method == "PUT":
            scene = self.combat.connect_landmarks(
                self._combat_guild_id(),
                self._text(body, "source_landmark_id"),
                self._text(body, "destination_landmark_id"),
                self._text(body, "distance"),
                obstacle=self._optional_text(body, "obstacle"),
                blocked=self._boolean(body, "blocked", default=False),
            )
            return 200, _combat_state_data(scene, self.world)
        if path == "/api/combat/routes" and method == "DELETE":
            scene = self.combat.disconnect_landmarks(
                self._combat_guild_id(),
                self._text(body, "source_landmark_id"),
                self._text(body, "destination_landmark_id"),
            )
            return 200, _combat_state_data(scene, self.world)

        if path == "/api/combat/enemies" and method == "POST":
            scene = self.combat.add_enemies(
                self._combat_guild_id(),
                self._text(body, "template_id"),
                landmark_id=self._optional_text(body, "landmark_id"),
                quantity=self._integer(body, "quantity", default=1),
            )
            return 201, _combat_state_data(scene, self.world)

        if path == "/api/combat/turn/next" and method == "POST":
            scene = self.combat.next_turn(self._combat_guild_id())
            return 200, _combat_state_data(scene, self.world)
        if path == "/api/combat/turn/previous" and method == "POST":
            scene = self.combat.previous_turn(self._combat_guild_id())
            return 200, _combat_state_data(scene, self.world)
        if path == "/api/combat/turn" and method == "PUT":
            scene = self.combat.jump_turn(
                self._combat_guild_id(),
                self._text(body, "kind"),
                self._text(body, "source_id"),
            )
            return 200, _combat_state_data(scene, self.world)

        initiative_match = re.fullmatch(
            r"/api/combat/initiative/(character|enemy)/([^/]+)",
            path,
        )
        if initiative_match and method == "PATCH":
            kind, source_id = initiative_match.groups()
            if "initiative_score" not in body:
                raise ValueError("'initiative_score' is required.")
            scene = self.combat.set_initiative(
                self._combat_guild_id(),
                kind,
                source_id,
                self._integer(body, "initiative_score", default=0),
            )
            return 200, _combat_state_data(scene, self.world)

        inspect_match = re.fullmatch(
            r"/api/combat/combatants/(character|enemy)/([^/]+)/inspect",
            path,
        )
        if inspect_match and method == "GET":
            kind, source_id = inspect_match.groups()
            scene = self.combat.current(self._combat_guild_id())
            if scene is None:
                return 404, {"error": "There is no active combat scene."}
            if not any(
                combatant.kind.value == kind
                and combatant.source_id == source_id
                for combatant in scene.combatants
            ):
                return 404, {
                    "error": (
                        f"Combatant '{kind}:{source_id}' is not in the active combat."
                    )
                }
            data = _combatant_inspect_data(
                self.world,
                kind,
                source_id,
                scene.room_id,
            )
            if data is None:
                return 404, {
                    "error": (
                        f"Combatant '{kind}:{source_id}' could not be inspected."
                    )
                }
            return 200, data

        if path == "/api/combat/actions/attack" and method == "POST":
            scene, result = self.combat.attack_enemy(
                self._combat_guild_id(),
                self._text(body, "target_enemy_id"),
            )
            payload = _combat_state_data(scene, self.world)
            payload["attack_result"] = _attack_result_data(result)
            return 200, payload

        if path == "/api/combat/actions/enemy-attack" and method == "POST":
            scene, result = self.combat.attack_character(
                self._combat_guild_id(),
                self._text(body, "target_character_id"),
            )
            payload = _combat_state_data(scene, self.world)
            payload["enemy_attack_result"] = _enemy_attack_result_data(result)
            return 200, payload

        movement_match = re.fullmatch(
            r"/api/combat/movement/(character|enemy)/([^/]+)",
            path,
        )
        if movement_match and method == "PATCH":
            kind, source_id = movement_match.groups()
            scene = self.combat.move_combatant_toward(
                self._combat_guild_id(),
                kind,
                source_id,
                self._text(body, "landmark_id"),
                self._text(body, "relation"),
            )
            return 200, _combat_state_data(scene, self.world)

        match = re.fullmatch(
            r"/api/combat/combatants/(character|enemy)/([^/]+)",
            path,
        )
        if match and method == "PATCH":
            kind, source_id = match.groups()
            scene = self.combat.move_combatant(
                self._combat_guild_id(),
                kind,
                source_id,
                self._text(body, "landmark_id"),
                self._text(body, "relation"),
            )
            return 200, _combat_state_data(scene, self.world)
        if match and method == "DELETE":
            kind, source_id = match.groups()
            if kind != "enemy":
                raise ValueError(
                    "Characters cannot be removed from combat through this endpoint."
                )
            scene = self.combat.remove_enemy(
                self._combat_guild_id(),
                source_id,
            )
            return 200, _combat_state_data(scene, self.world)

        if method == "GET" and path == "/api/characters":
            return 200, [
                _character_data(character) for character in self.world.list_characters()
            ]

        if method == "GET" and path == "/api/items":
            return 200, [
                _template_data(template)
                for template in sorted(
                    self.world.list_item_templates(),
                    key=lambda template: (template.name.casefold(), template.template_id),
                )
            ]

        if method == "POST" and path == "/api/items":
            record = self._item_record(body)
            template = self.world.create_item_template(record)
            return 201, _template_data(template)

        match = re.fullmatch(r"/api/items/([^/]+)", path)
        if method == "PUT" and match:
            record = self._item_record({**body, "id": match.group(1)})
            template = self.world.update_item_template(match.group(1), record)
            return 200, _template_data(template)

        if method == "GET" and path == "/api/container-templates":
            return 200, [
                _container_template_data(template)
                for template in self.world.list_container_templates()
            ]

        if method == "POST" and path == "/api/container-templates":
            default_is_locked = self._boolean(
                body, "default_is_locked", default=False
            )
            default_is_broken = self._boolean(
                body, "default_is_broken", default=False
            )
            default_has_lock = self._boolean(
                body,
                "default_has_lock",
                default=default_is_locked or default_is_broken,
            )
            default_hidden = self._boolean(
                body, "default_hidden", default=False
            )
            template = self.world.create_container_template(
                self._text(body, "id"),
                self._text(body, "name"),
                self._text(body, "type"),
                self._optional_text(body, "description"),
                default_has_lock=default_has_lock,
                default_is_locked=default_is_locked,
                default_is_broken=default_is_broken,
                default_unlock_difficulty=(
                    self._integer(
                        body, "default_unlock_difficulty", default=10
                    )
                    if default_is_locked
                    else None
                ),
                default_hidden=default_hidden,
                default_discovery_difficulty=(
                    self._integer(
                        body, "default_discovery_difficulty", default=10
                    )
                    if default_hidden
                    else None
                ),
            )
            return 201, _container_template_data(template)

        match = re.fullmatch(r"/api/container-templates/([^/]+)", path)
        if method == "PUT" and match:
            current = self.world.get_container_template(match.group(1))
            if current is None:
                raise ValueError(
                    f"Container template '{match.group(1)}' does not exist."
                )
            default_is_locked = self._boolean(
                body,
                "default_is_locked",
                default=current.default_is_locked,
            )
            default_is_broken = self._boolean(
                body,
                "default_is_broken",
                default=current.default_is_broken,
            )
            default_has_lock = self._boolean(
                body,
                "default_has_lock",
                default=current.default_has_lock,
            )
            default_hidden = self._boolean(
                body,
                "default_hidden",
                default=current.default_hidden,
            )
            template = self.world.update_container_template(
                match.group(1),
                self._text(body, "name")
                if "name" in body
                else current.name,
                self._text(body, "type")
                if "type" in body
                else current.container_type.value,
                (
                    self._optional_text(body, "description")
                    if "description" in body
                    else current.description
                ),
                default_has_lock=default_has_lock,
                default_is_locked=default_is_locked,
                default_is_broken=default_is_broken,
                default_unlock_difficulty=(
                    self._integer(
                        body,
                        "default_unlock_difficulty",
                        default=current.default_unlock_difficulty or 10,
                    )
                    if default_is_locked
                    else None
                ),
                default_hidden=default_hidden,
                default_discovery_difficulty=(
                    self._integer(
                        body,
                        "default_discovery_difficulty",
                        default=current.default_discovery_difficulty or 10,
                    )
                    if default_hidden
                    else None
                ),
            )
            return 200, _container_template_data(template)

        if method == "GET" and path == "/api/enemy-templates":
            return 200, [
                _enemy_template_data(template)
                for template in self.world.list_enemy_templates()
            ]

        if method == "POST" and path == "/api/enemy-templates":
            template = self.world.create_enemy_template(
                self._enemy_template_from_body(body)
            )
            return 201, _enemy_template_data(template)

        match = re.fullmatch(
            r"/api/enemy-templates/([^/]+)", path
        )
        if match and method == "GET":
            template = self.world.get_enemy_template(
                match.group(1)
            )
            if template is None:
                return 404, {
                    "error": (
                        f"Enemy template '{match.group(1)}' "
                        "does not exist."
                    )
                }
            return 200, _enemy_template_data(template)

        if match and method == "PUT":
            current = self.world.get_enemy_template(
                match.group(1)
            )
            if current is None:
                return 404, {
                    "error": (
                        f"Enemy template '{match.group(1)}' "
                        "does not exist."
                    )
                }
            template = self.world.update_enemy_template(
                current.template_id,
                self._enemy_template_from_body(
                    body,
                    template_id=current.template_id,
                    current=current,
                ),
            )
            return 200, _enemy_template_data(template)

        if match and method == "DELETE":
            self.world.remove_enemy_template(match.group(1))
            return 200, {"deleted": match.group(1)}

        if method == "GET" and path == "/api/room-feature-templates":
            return 200, [
                _room_feature_template_data(template)
                for template in self.world.list_room_feature_templates()
            ]

        if method == "POST" and path == "/api/room-feature-templates":
            template = self.world.create_room_feature_template(
                self._text(body, "id"),
                self._text(body, "name"),
                self._text(body, "feature_type"),
                self._optional_text(body, "description"),
            )
            return 201, _room_feature_template_data(template)

        match = re.fullmatch(r"/api/room-feature-templates/([^/]+)", path)
        if match and method == "GET":
            template = self.world.get_room_feature_template(match.group(1))
            if template is None:
                return 404, {
                    "error": (
                        f"Room feature template '{match.group(1)}' does not exist."
                    )
                }
            return 200, _room_feature_template_data(template)
        if match and method == "PATCH":
            current = self.world.get_room_feature_template(match.group(1))
            if current is None:
                return 404, {
                    "error": (
                        f"Room feature template '{match.group(1)}' does not exist."
                    )
                }
            template = self.world.update_room_feature_template(
                current.id,
                name=(
                    self._text(body, "name")
                    if "name" in body
                    else current.name
                ),
                description=(
                    self._optional_text(body, "description")
                    if "description" in body
                    else current.description
                ),
                feature_type=(
                    self._text(body, "feature_type")
                    if "feature_type" in body
                    else current.feature_type.value
                ),
            )
            return 200, _room_feature_template_data(template)
        if match and method == "DELETE":
            current = self.world.get_room_feature_template(match.group(1))
            if current is None:
                return 404, {
                    "error": (
                        f"Room feature template '{match.group(1)}' does not exist."
                    )
                }
            self.world.remove_room_feature_template(current.id)
            return 200, {"deleted": current.id}

        match = re.fullmatch(r"/api/characters/(\d+)/room", path)
        if method == "PATCH" and match:
            character_id = int(match.group(1))
            room = self.world.place_character(
                character_id, self._text(body, "room_id")
            )
            return 200, {"id": character_id, "current_room_id": room.id}

        if method == "GET" and path == "/api/areas":
            return 200, [
                {
                    "id": area.id,
                    "name": area.name,
                    "description": area.description or "",
                    "room_count": len(area.room_ids),
                }
                for area in self.world.list_areas()
            ]

        if method == "POST" and path == "/api/areas":
            area = self.world.create_area(
                self._text(body, "id"),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 201, {"id": area.id, "name": area.name, "description": area.description or ""}

        match = re.fullmatch(r"/api/areas/([^/]+)/graph", path)
        if method == "GET" and match:
            graph = _graph_data(
                self.world.area_graph(match.group(1)), self.room_images
            )
            for node in graph["nodes"]:
                room_id = str(node["id"])
                containers = self.world.list_room_containers(room_id)
                node["containers"] = [
                    _container_data(
                        container,
                        self.world.inventory(InventoryHolder.entity(container.id)),
                    )
                    for container in containers
                ]
                node["counts"]["containers"] = len(containers)

                room = self.world.get_room(room_id)
                enemy_instances = {
                    enemy.id: enemy
                    for enemy in self.world.list_room_enemies(room_id)
                }
                enemy_data: list[JsonObject] = []
                if room is not None:
                    for entity in room.enemies:
                        enemy = enemy_instances.get(entity.id)
                        if enemy is None:
                            enemy_data.append(
                                _legacy_enemy_data(entity)
                            )
                            continue
                        template = self.world.get_enemy_template(
                            enemy.template_id
                        )
                        if template is None:
                            enemy_data.append(
                                _legacy_enemy_data(entity)
                            )
                            continue
                        enemy_data.append(
                            _enemy_data(enemy, template)
                        )
                node["enemies"] = enemy_data

                room_features = self.world.list_room_features(room_id)
                node["room_features"] = [
                    _room_feature_data(feature) for feature in room_features
                ]
                node["counts"]["room_features"] = len(room_features)
            for connection in graph["connections"]:
                key = (
                    str(connection["source_room_id"]),
                    str(connection["exit_name"]),
                )
                if key in self._connection_trap_damage:
                    connection["trap_damage"] = self._connection_trap_damage[key]
            return 200, graph

        match = re.fullmatch(r"/api/areas/([^/]+)/rooms", path)
        if method == "POST" and match:
            room = self.world.create_room(
                self._text(body, "id"),
                match.group(1),
                self._text(body, "name"),
                self._optional_text(body, "description"),
                editor_x=self._number(body, "x"),
                editor_y=self._number(body, "y"),
            )
            return 201, {"id": room.id}

        match = re.fullmatch(r"/api/rooms/([^/]+)/image", path)
        if match and method == "DELETE":
            room = self.world.get_room(match.group(1))
            if room is None:
                return 404, {"error": f"Room '{match.group(1)}' does not exist."}
            self.world.set_room_scene_image(room.id, None)
            self.room_images.remove(room.scene_image_path)
            return 200, {"id": room.id, "room_image_url": None}

        match = re.fullmatch(r"/api/rooms/([^/]+)", path)
        if match and method == "PATCH":
            room = self.world.update_room(
                match.group(1),
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 200, {"id": room.id, "name": room.name, "description": room.description or ""}
        if match and method == "DELETE":
            room = self.world.get_room(match.group(1))
            self.world.delete_room(match.group(1))
            if room is not None:
                self.room_images.remove(room.scene_image_path)
            return 200, {"deleted": match.group(1)}

        match = re.fullmatch(r"/api/rooms/([^/]+)/position", path)
        if match and method == "PATCH":
            self.world.set_room_editor_position(
                match.group(1), self._number(body, "x"), self._number(body, "y")
            )
            return 200, {"id": match.group(1), "position": {"x": body["x"], "y": body["y"]}}

        match = re.fullmatch(r"/api/rooms/([^/]+)/features", path)
        if match and method == "GET":
            return 200, [
                _room_feature_data(feature)
                for feature in self.world.list_room_features(match.group(1))
            ]
        if match and method == "POST":
            feature = self.world.create_room_feature(
                match.group(1),
                self._text(body, "id"),
                self._text(body, "name"),
                self._text(body, "feature_type"),
                self._optional_text(body, "description"),
            )
            return 201, _room_feature_data(feature)

        match = re.fullmatch(r"/api/room-features/([^/]+)", path)
        if match and method == "GET":
            feature = self.world.get_room_feature(match.group(1))
            if feature is None:
                return 404, {
                    "error": f"Room feature '{match.group(1)}' does not exist."
                }
            return 200, _room_feature_data(feature)
        if match and method == "PATCH":
            current = self.world.get_room_feature(match.group(1))
            if current is None:
                return 404, {
                    "error": f"Room feature '{match.group(1)}' does not exist."
                }
            feature = self.world.update_room_feature(
                current.id,
                name=(
                    self._text(body, "name")
                    if "name" in body
                    else current.name
                ),
                description=(
                    self._optional_text(body, "description")
                    if "description" in body
                    else current.description
                ),
                feature_type=(
                    self._text(body, "feature_type")
                    if "feature_type" in body
                    else current.feature_type.value
                ),
            )
            return 200, _room_feature_data(feature)
        if match and method == "DELETE":
            self.world.remove_room_feature(match.group(1))
            return 200, {"deleted": match.group(1)}

        match = re.fullmatch(r"/api/rooms/([^/]+)/containers", path)
        if match and method == "POST":
            room_id = match.group(1)
            template_id = self._text(body, "template_id")
            template = self.world.get_container_template(template_id)
            if template is None:
                raise ValueError(
                    f"Container template '{template_id}' does not exist."
                )
            has_lock = (
                self._boolean(body, "has_lock", default=template.default_has_lock)
                if "has_lock" in body
                else None
            )
            is_locked = (
                self._boolean(
                    body, "is_locked", default=template.default_is_locked
                )
                if "is_locked" in body
                else None
            )
            is_broken = (
                self._boolean(
                    body, "is_broken", default=template.default_is_broken
                )
                if "is_broken" in body
                else None
            )
            hidden = (
                self._boolean(
                    body, "hidden", default=template.default_hidden
                )
                if "hidden" in body
                else None
            )
            instance = self.world.place_container(
                room_id,
                template_id,
                instance_id=self._optional_text(body, "id"),
                name=self._optional_text(body, "name"),
                description=(
                    self._optional_text(body, "description")
                    if "description" in body
                    else None
                ),
                has_lock=has_lock,
                is_locked=is_locked,
                is_broken=is_broken,
                unlock_difficulty=(
                    self._integer(
                        body,
                        "unlock_difficulty",
                        default=template.default_unlock_difficulty or 10,
                    )
                    if (
                        (is_locked is True)
                        or (is_locked is None and template.default_is_locked)
                    )
                    else None
                ),
                hidden=hidden,
                discovery_difficulty=(
                    self._integer(
                        body,
                        "discovery_difficulty",
                        default=template.default_discovery_difficulty or 10,
                    )
                    if (
                        (hidden is True)
                        or (hidden is None and template.default_hidden)
                    )
                    else None
                ),
                is_open=self._boolean(body, "is_open", default=False),
                searched=self._boolean(body, "searched", default=False),
            )
            return 201, _container_data(
                instance,
                self.world.inventory(InventoryHolder.entity(instance.id)),
            )

        match = re.fullmatch(r"/api/containers/([^/]+)", path)
        if match and method == "GET":
            instance = self.world.get_container(match.group(1))
            if instance is None:
                return 404, {
                    "error": f"Container '{match.group(1)}' does not exist."
                }
            return 200, _container_data(
                instance,
                self.world.inventory(InventoryHolder.entity(instance.id)),
            )
        if match and method == "PATCH":
            current = self.world.get_container(match.group(1))
            if current is None:
                raise ValueError(
                    f"Container '{match.group(1)}' does not exist."
                )
            has_lock = self._boolean(
                body, "has_lock", default=current.has_lock
            )
            is_locked = self._boolean(
                body, "is_locked", default=current.is_locked
            )
            is_broken = self._boolean(
                body, "is_broken", default=current.is_broken
            )
            hidden = self._boolean(
                body, "hidden", default=current.hidden
            )
            updated = self.world.update_container(
                current.id,
                name=(
                    self._text(body, "name")
                    if "name" in body
                    else current.name
                ),
                description=(
                    self._optional_text(body, "description")
                    if "description" in body
                    else current.description
                ),
                has_lock=has_lock,
                is_locked=is_locked,
                is_broken=is_broken,
                unlock_difficulty=(
                    self._integer(
                        body,
                        "unlock_difficulty",
                        default=current.unlock_difficulty or 10,
                    )
                    if is_locked
                    else None
                ),
                hidden=hidden,
                discovery_difficulty=(
                    self._integer(
                        body,
                        "discovery_difficulty",
                        default=current.discovery_difficulty or 10,
                    )
                    if hidden
                    else None
                ),
                is_open=self._boolean(
                    body, "is_open", default=current.is_open
                ),
                searched=self._boolean(
                    body, "searched", default=current.searched
                ),
            )
            return 200, _container_data(
                updated,
                self.world.inventory(InventoryHolder.entity(updated.id)),
            )
        if match and method == "DELETE":
            self.world.remove_container(match.group(1))
            return 200, {"deleted": match.group(1)}

        match = re.fullmatch(r"/api/containers/([^/]+)/items", path)
        if match and method == "POST":
            container_id = match.group(1)
            if self.world.get_container(container_id) is None:
                raise ValueError(
                    f"Container '{container_id}' does not exist."
                )
            quantity = self._integer(body, "quantity", default=1)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            stack = self.world.place_catalog_item(
                InventoryHolder.entity(container_id),
                self._text(body, "item_id"),
                quantity,
            )
            return 201, _stack_data(stack)

        match = re.fullmatch(
            r"/api/containers/([^/]+)/items/([^/]+)", path
        )
        if match and method == "PUT":
            container_id, item_id = match.groups()
            quantity = self._integer(body, "quantity", default=1)
            stack = self.world.set_item_quantity(
                InventoryHolder.entity(container_id),
                item_id,
                quantity,
            )
            return 200, _stack_data(stack)
        if match and method == "DELETE":
            container_id, item_id = match.groups()
            self.world.remove_item(
                InventoryHolder.entity(container_id), item_id
            )
            return 200, {"deleted": item_id}

        match = re.fullmatch(
            r"/api/rooms/([^/]+)/enemies", path
        )
        if match and method == "POST":
            enemy = self.world.place_enemy(
                match.group(1),
                self._text(body, "template_id"),
                instance_id=self._optional_text(body, "id"),
                name=self._optional_text(body, "name"),
                description=self._optional_text(
                    body, "description"
                ),
            )
            template = self.world.get_enemy_template(
                enemy.template_id
            )
            assert template is not None
            return 201, _enemy_data(enemy, template)

        match = re.fullmatch(r"/api/enemies/([^/]+)", path)
        if match and method == "GET":
            enemy = self.world.get_enemy(match.group(1))
            if enemy is None:
                return 404, {
                    "error": (
                        f"Enemy '{match.group(1)}' does not exist."
                    )
                }
            template = self.world.get_enemy_template(
                enemy.template_id
            )
            assert template is not None
            return 200, _enemy_data(enemy, template)

        if match and method == "PATCH":
            current = self.world.get_enemy(match.group(1))
            if current is None:
                return 404, {
                    "error": (
                        f"Enemy '{match.group(1)}' does not exist."
                    )
                }
            enemy = self.world.update_enemy(
                current.id,
                name=(
                    self._text(body, "name")
                    if "name" in body
                    else current.name
                ),
                description=(
                    self._optional_text(body, "description")
                    if "description" in body
                    else current.description
                ),
                current_hp=self._integer(
                    body,
                    "current_hp",
                    default=current.current_hp,
                ),
                status=(
                    self._optional_text(body, "status")
                    if "status" in body
                    else None
                ),
            )
            template = self.world.get_enemy_template(
                enemy.template_id
            )
            assert template is not None
            return 200, _enemy_data(enemy, template)

        if match and method == "DELETE":
            current = self.world.get_enemy(match.group(1))
            if current is None:
                return 404, {
                    "error": (
                        f"Enemy '{match.group(1)}' does not exist."
                    )
                }
            self.world.remove_entity(current.id)
            return 200, {"deleted": current.id}

        match = re.fullmatch(r"/api/rooms/([^/]+)/entities", path)
        if match and method == "POST":
            try:
                kind = EntityKind(self._text(body, "kind"))
            except ValueError as error:
                raise ValueError("Entity kind must be enemy, npc, or container.") from error
            entity = self.world.create_entity(
                self._text(body, "id"),
                match.group(1),
                kind,
                self._text(body, "name"),
                self._optional_text(body, "description"),
            )
            return 201, asdict(entity)

        match = re.fullmatch(r"/api/rooms/([^/]+)/entities/([^/]+)", path)
        if match and method == "DELETE":
            room_id, entity_id = match.groups()
            room = self.world.get_room(room_id)
            if room is None:
                raise ValueError(f"Room '{room_id}' does not exist.")
            if not any(entity.id == entity_id for entity in room.entities):
                raise ValueError(
                    f"Entity '{entity_id}' does not exist in room '{room_id}'."
                )
            self.world.remove_entity(entity_id)
            return 200, {"deleted": entity_id}

        match = re.fullmatch(r"/api/rooms/([^/]+)/items", path)
        if match and method == "POST":
            room_id = match.group(1)
            if self.world.get_room(room_id) is None:
                raise ValueError(f"Room '{room_id}' does not exist.")
            quantity = self._integer(body, "quantity", default=1)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than zero.")
            stack = self.world.place_catalog_item(
                InventoryHolder.room(room_id),
                self._text(body, "item_id"),
                quantity,
            )
            return 201, _stack_data(stack)

        match = re.fullmatch(r"/api/rooms/([^/]+)/items/([^/]+)", path)
        if match and method == "DELETE":
            room_id, item_id = match.groups()
            self.world.remove_item(InventoryHolder.room(room_id), item_id)
            return 200, {"deleted": item_id}

        if path == "/api/connections" and method == "POST":
            exit_name = self._text(body, "exit_name")
            connection_type = self._connection_type(
                body, default=ConnectionType.HALLWAY
            )
            is_locked = self._boolean(body, "is_locked", default=False)
            is_broken = self._boolean(body, "is_broken", default=False)
            has_lock = self._boolean(
                body, "has_lock", default=is_locked or is_broken
            )
            unlock_difficulty = (
                self._integer(body, "unlock_difficulty", default=10)
                if is_locked
                else None
            )
            self._validate_door_lock(
                connection_type, has_lock, is_locked, is_broken, unlock_difficulty
            )
            is_open = self._boolean(body, "is_open", default=False)
            self._validate_door_open(connection_type, is_open, is_locked)
            has_trap = self._boolean(body, "has_trap", default=False)
            trap_state = (
                self._trap_state(body, default=TrapState.ARMED)
                if has_trap
                else None
            )
            trap_detection_difficulty = (
                self._integer(body, "trap_detection_difficulty", default=10)
                if has_trap
                else None
            )
            trap_disarm_difficulty = (
                self._integer(body, "trap_disarm_difficulty", default=10)
                if has_trap
                else None
            )
            trap_damage_type = (
                self._trap_damage_type(body, default=TrapDamageType.PHYSICAL)
                if has_trap
                else None
            )
            trap_damage = (
                self._integer(body, "trap_damage", default=1)
                if has_trap
                else None
            )
            self._validate_trap(
                has_trap,
                trap_detection_difficulty,
                trap_disarm_difficulty,
                trap_damage_type,
                trap_damage,
            )
            bidirectional = self._boolean(body, "bidirectional", default=True)
            return_exit_name = (
                self._optional_text(body, "return_exit_name") or exit_name
                if bidirectional
                else None
            )
            connection = self.world.connect_rooms(
                self._text(body, "source_room_id"),
                exit_name,
                self._text(body, "destination_room_id"),
                return_exit_name=return_exit_name,
                connection_type=connection_type,
                has_lock=has_lock,
                is_locked=is_locked,
                is_broken=is_broken,
                is_open=is_open,
                unlock_difficulty=unlock_difficulty,
                has_trap=has_trap,
                trap_state=trap_state,
                trap_detection_difficulty=trap_detection_difficulty,
                trap_disarm_difficulty=trap_disarm_difficulty,
                trap_damage_type=trap_damage_type,
                trap_damage=trap_damage,
            )
            if has_trap and trap_damage is not None:
                self._connection_trap_damage[
                    (self._text(body, "source_room_id"), exit_name)
                ] = trap_damage
            return 201, {
                "connection_id": connection.id,
                "source_room_id": body["source_room_id"],
                "exit_name": exit_name,
                "destination_room_id": body["destination_room_id"],
                "return_exit_name": return_exit_name,
                "bidirectional": bidirectional,
                "connection_type": connection_type.value,
                "has_lock": has_lock,
                "is_locked": is_locked,
                "is_broken": is_broken,
                "is_open": is_open,
                "unlock_difficulty": unlock_difficulty,
                "has_trap": has_trap,
                "trap_state": trap_state.value if trap_state is not None else None,
                "trap_detection_difficulty": trap_detection_difficulty,
                "trap_disarm_difficulty": trap_disarm_difficulty,
                "trap_damage_type": (
                    trap_damage_type.value if trap_damage_type is not None else None
                ),
                "trap_damage": trap_damage,
            }
        if path == "/api/connections" and method == "PATCH":
            source_room_id = self._text(body, "source_room_id")
            exit_name = self._text(body, "exit_name")
            bidirectional = self._boolean(body, "bidirectional", default=True)
            return_exit_name = (
                self._optional_text(body, "return_exit_name") or exit_name
                if bidirectional
                else None
            )
            connection_type = (
                self._connection_type(body) if "connection_type" in body else None
            )
            open_was_supplied = "is_open" in body
            is_open = self._boolean(body, "is_open", default=False)
            lock_was_supplied = (
                "has_lock" in body
                or "is_locked" in body
                or "is_broken" in body
                or "unlock_difficulty" in body
            )
            is_locked = self._boolean(body, "is_locked", default=False)
            is_broken = self._boolean(body, "is_broken", default=False)
            has_lock = self._boolean(
                body, "has_lock", default=is_locked or is_broken
            )
            unlock_difficulty = (
                self._integer(body, "unlock_difficulty", default=10)
                if is_locked
                else None
            )
            trap_was_supplied = any(
                field in body
                for field in (
                    "has_trap",
                    "trap_state",
                    "trap_detection_difficulty",
                    "trap_disarm_difficulty",
                    "trap_damage_type",
                    "trap_damage",
                )
            )
            has_trap = self._boolean(body, "has_trap", default=False)
            trap_state = (
                self._trap_state(body, default=TrapState.ARMED)
                if has_trap
                else None
            )
            trap_detection_difficulty = (
                self._integer(body, "trap_detection_difficulty", default=10)
                if has_trap
                else None
            )
            trap_disarm_difficulty = (
                self._integer(body, "trap_disarm_difficulty", default=10)
                if has_trap
                else None
            )
            trap_damage_type = (
                self._trap_damage_type(body, default=TrapDamageType.PHYSICAL)
                if has_trap
                else None
            )
            trap_damage = (
                self._integer(body, "trap_damage", default=1)
                if has_trap
                else None
            )
            if is_locked and not 1 <= unlock_difficulty <= 30:
                raise ValueError("Unlock difficulty must be an integer from 1 to 30.")
            if connection_type is not None:
                self._validate_door_lock(
                    connection_type, has_lock, is_locked, is_broken,
                    unlock_difficulty
                )
                self._validate_door_open(connection_type, is_open, is_locked)
            elif is_open and is_locked:
                raise ValueError("A locked door cannot be open.")
            if trap_was_supplied:
                self._validate_trap(
                    has_trap,
                    trap_detection_difficulty,
                    trap_disarm_difficulty,
                    trap_damage_type,
                    trap_damage,
                )
            self.world.set_connection_direction(
                source_room_id,
                exit_name,
                bidirectional=bidirectional,
                return_exit_name=return_exit_name,
            )
            if connection_type is not None:
                self.world.set_connection_type(
                    source_room_id, exit_name, connection_type
                )
            if lock_was_supplied:
                self.world.set_connection_lock(
                    source_room_id,
                    exit_name,
                    has_lock=has_lock,
                    is_locked=is_locked,
                    is_broken=is_broken,
                    unlock_difficulty=unlock_difficulty,
                )
            if open_was_supplied:
                self.world.set_connection_open(
                    source_room_id,
                    exit_name,
                    is_open=is_open,
                )
            if trap_was_supplied:
                self.world.set_connection_trap(
                    source_room_id,
                    exit_name,
                    has_trap=has_trap,
                    trap_state=trap_state,
                    trap_detection_difficulty=trap_detection_difficulty,
                    trap_damage_type=trap_damage_type,
                    trap_damage=trap_damage,
                )
                self.world.set_connection_trap_disarm_difficulty(
                    source_room_id,
                    exit_name,
                    trap_disarm_difficulty,
                )
                trap_key = (source_room_id, exit_name)
                if has_trap and trap_damage is not None:
                    self._connection_trap_damage[trap_key] = trap_damage
                else:
                    self._connection_trap_damage.pop(trap_key, None)
            return 200, {
                "source_room_id": source_room_id,
                "exit_name": exit_name,
                "bidirectional": bidirectional,
                "return_exit_name": return_exit_name,
                **(
                    {"is_open": is_open} if open_was_supplied else {}
                ),
                **(
                    {"connection_type": connection_type.value}
                    if connection_type is not None
                    else {}
                ),
                **(
                    {
                        "has_trap": has_trap,
                        "trap_state": (
                            trap_state.value if trap_state is not None else None
                        ),
                        "trap_detection_difficulty": trap_detection_difficulty,
                        "trap_disarm_difficulty": trap_disarm_difficulty,
                        "trap_damage_type": (
                            trap_damage_type.value
                            if trap_damage_type is not None
                            else None
                        ),
                        "trap_damage": trap_damage,
                    }
                    if trap_was_supplied
                    else {}
                ),
                **(
                    {
                        "has_lock": has_lock,
                        "is_locked": is_locked,
                        "is_broken": is_broken,
                        "unlock_difficulty": unlock_difficulty,
                    }
                    if lock_was_supplied
                    else {}
                ),
            }
        if path == "/api/connections" and method == "DELETE":
            source_room_id = self._text(body, "source_room_id")
            exit_name = self._text(body, "exit_name")
            self.world.disconnect_connection(
                source_room_id, exit_name
            )
            self._connection_trap_damage.pop((source_room_id, exit_name), None)
            return 200, {"deleted": True}

        return 404, {"error": "Not found."}

    def _room_image_data(self, room: Room) -> JsonObject:
        path = self.room_images.path_for(room.scene_image_path)
        return {
            "id": room.id,
            "room_image_url": (
                f"/api/rooms/{quote(room.id, safe='')}/image"
                f"?version={quote(path.stem, safe='')}"
                if path is not None
                else room.scene_image_url
            ),
        }

    def _combat_guild_id(self) -> int:
        if self.guild_id is None or self.guild_id <= 0:
            raise ValueError(
                "Combat dashboard requires DISCORD_GUILD_ID or "
                "dashboard_server --guild-id."
            )
        return self.guild_id

    @staticmethod
    def _text(body: JsonObject, field: str) -> str:
        value = body.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' is required.")
        return value.strip()

    @staticmethod
    def _optional_text(body: JsonObject, field: str) -> str | None:
        value = body.get(field)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"'{field}' must be text.")
        return value.strip() or None

    @staticmethod
    def _connection_type(
        body: JsonObject,
        *,
        default: ConnectionType | None = None,
    ) -> ConnectionType:
        value = body.get("connection_type")
        if value is None and default is not None:
            return default
        try:
            connection_type = ConnectionType(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Connection type must be door or hallway.") from error
        if connection_type not in (ConnectionType.DOOR, ConnectionType.HALLWAY):
            raise ValueError("Connection type must be door or hallway.")
        return connection_type

    @staticmethod
    def _validate_door_lock(
        connection_type: ConnectionType,
        has_lock: bool,
        is_locked: bool,
        is_broken: bool,
        unlock_difficulty: int | None,
    ) -> None:
        if has_lock and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can have a lock.")
        if (is_locked or is_broken) and not has_lock:
            raise ValueError("A door without a lock cannot be locked or broken.")
        if is_locked and is_broken:
            raise ValueError("A broken lock cannot also be locked.")
        if is_locked and (
            unlock_difficulty is None or not 1 <= unlock_difficulty <= 30
        ):
            raise ValueError("Unlock difficulty must be an integer from 1 to 30.")

    @staticmethod
    def _validate_door_open(
        connection_type: ConnectionType,
        is_open: bool,
        is_locked: bool,
    ) -> None:
        if is_open and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can be open.")
        if is_open and is_locked:
            raise ValueError("A locked door cannot be open.")

    @staticmethod
    def _trap_damage_type(
        body: JsonObject,
        *,
        default: TrapDamageType,
    ) -> TrapDamageType:
        value = body.get("trap_damage_type", default.value)
        if isinstance(value, str):
            value = value.strip().casefold()
        try:
            return TrapDamageType(value)
        except (TypeError, ValueError) as error:
            allowed = ", ".join(item.value for item in TrapDamageType)
            raise ValueError(f"Trap damage type must be one of: {allowed}.") from error

    @staticmethod
    def _trap_state(
        body: JsonObject,
        *,
        default: TrapState,
    ) -> TrapState:
        value = body.get("trap_state", default.value)
        try:
            return TrapState(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Trap state must be armed, disarmed, or triggered."
            ) from error

    @staticmethod
    def _validate_trap(
        has_trap: bool,
        trap_detection_difficulty: int | None,
        trap_disarm_difficulty: int | None,
        trap_damage_type: TrapDamageType | None,
        trap_damage: int | None,
    ) -> None:
        if not has_trap:
            return
        if (
            trap_detection_difficulty is None
            or not 1 <= trap_detection_difficulty <= 30
        ):
            raise ValueError("Trap detection difficulty must be an integer from 1 to 30.")
        if trap_disarm_difficulty is None or not 1 <= trap_disarm_difficulty <= 30:
            raise ValueError("Trap disarm difficulty must be an integer from 1 to 30.")
        if trap_damage_type is None:
            raise ValueError("Trap damage type is required.")
        if trap_damage is None or trap_damage <= 0:
            raise ValueError("Trap damage must be a positive integer.")

    @staticmethod
    def _number(body: JsonObject, field: str) -> float:
        value = body.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"'{field}' must be a number.")
        return float(value)

    @staticmethod
    def _integer(body: JsonObject, field: str, *, default: int) -> int:
        value = body.get(field, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"'{field}' must be an integer.")
        return value

    @classmethod
    def _enemy_template_from_body(
        cls,
        body: JsonObject,
        *,
        template_id: str | None = None,
        current: EnemyTemplate | None = None,
    ) -> EnemyTemplate:
        def text_value(
            field: str,
            default: str,
        ) -> str:
            if field in body:
                return cls._text(body, field)
            return default

        def optional_value(
            field: str,
            default: str | None,
        ) -> str | None:
            if field in body:
                return cls._optional_text(body, field)
            return default

        return EnemyTemplate(
            template_id=(
                template_id or cls._text(body, "id")
            ),
            name=(
                cls._text(body, "name")
                if current is None or "name" in body
                else current.name
            ),
            description=optional_value(
                "description",
                (
                    current.description
                    if current is not None
                    else None
                ),
            ),
            race=text_value(
                "race",
                current.race if current is not None else "Unknown",
            ),
            difficulty_level=cls._integer(
                body,
                "difficulty_level",
                default=(
                    current.difficulty_level
                    if current is not None
                    else 1
                ),
            ),
            strength=cls._integer(
                body,
                "strength",
                default=current.strength if current is not None else 0,
            ),
            dexterity=cls._integer(
                body,
                "dexterity",
                default=current.dexterity if current is not None else 0,
            ),
            arcana=cls._integer(
                body,
                "arcana",
                default=current.arcana if current is not None else 0,
            ),
            vitality=cls._integer(
                body,
                "vitality",
                default=current.vitality if current is not None else 0,
            ),
            insight=cls._integer(
                body,
                "insight",
                default=current.insight if current is not None else 0,
            ),
            personality=cls._integer(
                body,
                "personality",
                default=(
                    current.personality
                    if current is not None
                    else 0
                ),
            ),
            max_hp=cls._integer(
                body,
                "max_hp",
                default=current.max_hp if current is not None else 7,
            ),
            armor=cls._integer(
                body,
                "armor",
                default=current.armor if current is not None else 0,
            ),
            magical_resistance=cls._integer(
                body,
                "magical_resistance",
                default=(
                    current.magical_resistance
                    if current is not None
                    else 0
                ),
            ),
            attack_dc=cls._integer(
                body,
                "attack_dc",
                default=current.attack_dc if current is not None else 12,
            ),
            defense_dc=cls._integer(
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
                (
                    current.attack_profile
                    if current is not None
                    else "Basic attack"
                ),
            ),
            special_ability=optional_value(
                "special_ability",
                (
                    current.special_ability
                    if current is not None
                    else None
                ),
            ),
            typical_behaviour=text_value(
                "typical_behaviour",
                (
                    current.typical_behaviour
                    if current is not None
                    else "Unknown"
                ),
            ),
            main_hand_item_id=optional_value(
                "main_hand_item_id",
                (
                    current.main_hand_item_id
                    if current is not None
                    else None
                ),
            ),
            off_hand_item_id=optional_value(
                "off_hand_item_id",
                (
                    current.off_hand_item_id
                    if current is not None
                    else None
                ),
            ),
            armor_item_id=optional_value(
                "armor_item_id",
                (
                    current.armor_item_id
                    if current is not None
                    else None
                ),
            ),
        )

    @classmethod
    def _item_record(cls, body: JsonObject) -> dict[str, object]:
        try:
            item_type = ItemType(cls._text(body, "item_type"))
        except ValueError as error:
            raise ValueError(
                "Item type must be weapon, armor, clothing, container, consumable, "
                "readable, tool, or misc."
            ) from error

        value = cls._integer(body, "value", default=0)
        weight = cls._integer(body, "weight", default=0)
        default_slot_cost = 0 if item_type is ItemType.READABLE and weight == 0 else 1
        slot_cost = cls._integer(body, "slot_cost", default=default_slot_cost)
        if value < 0 or weight < 0 or slot_cost < 0:
            raise ValueError("Item value, weight, and slot cost cannot be negative.")
        record: dict[str, object] = {
            "item_type": item_type.value,
            "id": cls._text(body, "id"),
            "name": cls._text(body, "name"),
            "rarity": cls._text_or_default(body, "rarity", "Common"),
            "value": value,
            "description": cls._optional_text(body, "description") or "",
            "weight": weight,
            "slot_cost": slot_cost,
            "tags": [
                (
                    "stackable"
                    if cls._boolean(
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
                grip = WeaponGrip(cls._text_or_default(body, "grip", "one_handed"))
            except ValueError as error:
                raise ValueError("Weapon grip must be one_handed or two_handed.") from error
            durability = cls._positive_integer(body, "durability", default=40)
            damage = cls._positive_integer(body, "damage", default=1)
            record.update(
                grip=grip.value,
                durability=durability,
                damage_parts=[
                    {
                        "amount": damage,
                        "damage_type": cls._text_or_default(
                            body, "damage_type", "physical"
                        ),
                    }
                ],
            )
        elif item_type is ItemType.ARMOR:
            protection = cls._positive_integer(body, "protection", default=1)
            strength_requirement = cls._integer(
                body, "strength_requirement", default=0
            )
            if strength_requirement < 0:
                raise ValueError("Strength requirement cannot be negative.")
            record.update(
                protection_current=protection,
                protection_max=protection,
                dodge_penalty=cls._integer(body, "dodge_penalty", default=0),
                strength_requirement=strength_requirement or None,
            )
        elif item_type is ItemType.CONTAINER:
            record.update(
                capacity=cls._positive_integer(body, "capacity", default=10),
                items=[],
                can_equip=cls._boolean(body, "can_equip", default=False),
                locked=False,
            )
        elif item_type is ItemType.CONSUMABLE:
            record.update(
                affected_stat="hp",
                affected_amount=cls._positive_integer(
                    body, "affected_amount", default=1
                ),
                side_effects=None,
            )
        elif item_type is ItemType.READABLE:
            content = body.get("content", "")
            if not isinstance(content, str):
                raise ValueError("'content' must be text.")
            record["content"] = content
        return record

    @staticmethod
    def _text_or_default(body: JsonObject, field: str, default: str) -> str:
        value = body.get(field, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' must be text.")
        return value.strip()

    @classmethod
    def _positive_integer(cls, body: JsonObject, field: str, *, default: int) -> int:
        value = cls._integer(body, field, default=default)
        if value <= 0:
            raise ValueError(f"'{field}' must be greater than zero.")
        return value

    @staticmethod
    def _boolean(body: JsonObject, field: str, *, default: bool) -> bool:
        value = body.get(field, default)
        if not isinstance(value, bool):
            raise ValueError(f"'{field}' must be true or false.")
        return value
