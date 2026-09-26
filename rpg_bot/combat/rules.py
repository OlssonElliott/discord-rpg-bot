"""Shared combat rules derived from character and enemy state."""

from __future__ import annotations

from .errors import CombatError
from ..inventory import EquipmentSlot, ItemTemplate, ItemType


class CombatRulesMixin:
    """Shared combat lookups, derived stats, equipment, and defense rules."""

    def _character_insight_modifier(self, character_id: int) -> int:
        insight = self.database.get_character_attribute(character_id, "insight")
        return (insight - 10) // 2

    def _enemy_insight_modifier(self, enemy_id: str) -> int:
        enemy = self.world.get_enemy(enemy_id)
        if enemy is None:
            return 0
        template = self.world.get_enemy_template(enemy.template_id)
        return template.insight if template is not None else 0

    def _character_load_state(self, character_id: int) -> str:
        inventory = self.database.get_character_inventory(character_id)
        capacity = max(1, inventory.carry_capacity())
        weight = inventory.current_weight(self.world.catalog)
        if weight > capacity:
            return "over_encumbered"
        if weight * 4 > capacity * 3:
            return "encumbered"
        return "normal"

    def _character_movement_budget(self, character_id: int) -> int:
        dexterity = self.database.get_character_attribute(
            character_id,
            "dexterity",
        )
        dexterity_modifier = (dexterity - 10) // 2
        movement = max(1, 2 + dexterity_modifier // 2)

        load_state = self._character_load_state(character_id)
        if load_state == "over_encumbered":
            return 1
        if load_state == "encumbered":
            movement -= 1
        return max(1, movement)

    def _enemy_movement_budget(self, enemy_id: str) -> int:
        enemy = self.world.get_enemy(enemy_id)
        if enemy is None:
            return 2
        template = self.world.get_enemy_template(enemy.template_id)
        dexterity_modifier = template.dexterity if template is not None else 0
        return max(1, 2 + dexterity_modifier // 2)

    def _character_by_source_id(self, source_id: str):
        try:
            character_id = int(source_id)
        except ValueError as error:
            raise CombatError(
                f"Character combatant '{source_id}' is invalid."
            ) from error
        character = next(
            (
                candidate
                for candidate in self.database.list_all_characters()
                if candidate.character_id == character_id
            ),
            None,
        )
        if character is None:
            raise CombatError(
                f"Character {character_id} does not exist."
            )
        return character

    def _equipped_attack_weapon(
        self,
        character_id: int,
    ) -> ItemTemplate | None:
        inventory = self.database.get_character_inventory(character_id)
        for slot in (EquipmentSlot.MAIN_HAND, EquipmentSlot.OFF_HAND):
            instance_id = inventory.equipment.get(slot)
            if instance_id is None:
                continue
            instance = next(
                (
                    item
                    for item in inventory.items
                    if item.instance_id == instance_id
                ),
                None,
            )
            if instance is None or instance.durability == 0:
                continue
            try:
                template = self.world.catalog.get(instance.template_id)
            except ValueError:
                continue
            if template.item_type is ItemType.WEAPON:
                return template
        return None

    @staticmethod
    def _weapon_attack_attribute(
        weapon: ItemTemplate | None,
    ) -> str:
        if weapon is None:
            return "strength"
        tags = {tag.casefold() for tag in weapon.tags}
        if tags & {"magic", "spell", "focus", "staff"}:
            return "arcana"
        if tags & {
            "bow",
            "crossbow",
            "ranged",
            "finesse",
            "dagger",
            "light",
        }:
            return "dexterity"
        return "strength"

    def _equipped_armor_stats(
        self,
        character_id: int,
    ) -> tuple[int, int]:
        inventory = self.database.get_character_inventory(character_id)
        armor_id = inventory.equipment.get(EquipmentSlot.ARMOR)
        if armor_id is None:
            return 0, 0
        try:
            instance = inventory.item(armor_id)
            template = self.world.catalog.get(instance.template_id)
        except ValueError:
            return 0, 0
        if template.item_type is not ItemType.ARMOR:
            return 0, 0
        protection = (
            instance.durability
            if instance.durability is not None
            else template.protection or 0
        )
        return max(0, protection), template.dodge_penalty

    def _automatic_defense(
        self,
        character_id: int,
    ) -> tuple[str, str, int]:
        _, dodge_penalty = self._equipped_armor_stats(character_id)
        strength = self.database.get_character_attribute(
            character_id,
            "strength",
        )
        dexterity = self.database.get_character_attribute(
            character_id,
            "dexterity",
        )
        arcana = self.database.get_character_attribute(
            character_id,
            "arcana",
        )
        options = (
            ("guard", "strength", (strength - 10) // 2),
            (
                "dodge",
                "dexterity",
                (dexterity - 10) // 2 + dodge_penalty,
            ),
            ("arcane_defense", "arcana", (arcana - 10) // 2),
        )
        return max(options, key=lambda option: option[2])
