"""Validated inventory operations independent of Discord UI."""

from __future__ import annotations

from dataclasses import replace

from .database import Database
from .inventory import (
    EquipmentSlot,
    InventoryState,
    ItemCatalog,
    ItemInstance,
    ItemType,
    WeaponGrip,
)
from .models import Character


class InventoryError(ValueError):
    pass


class InventoryService:
    def __init__(self, database: Database, catalog: ItemCatalog) -> None:
        self.database = database
        self.catalog = catalog

    def grant(self, character: Character, template_id: str, quantity: int = 1) -> str:
        if character.character_id is None:
            raise InventoryError("The character has not been saved.")
        template = self.catalog.get(template_id)
        if quantity <= 0:
            raise InventoryError("Quantity must be greater than zero.")
        if not template.stackable and quantity != 1:
            raise InventoryError("Only consumables can be granted as a stack.")
        inventory = self.database.get_character_inventory(character.character_id)
        added_weight = template.weight * quantity
        if (
            inventory.current_storage(self.catalog) + added_weight
            > inventory.storage_capacity(self.catalog)
        ):
            raise InventoryError("There is not enough inventory space.")
        return self.database.add_inventory_item(
            character.character_id,
            template_id,
            quantity=quantity,
            durability=template.durability,
            stackable=template.stackable,
        )

    def equip(
        self,
        character: Character,
        instance_id: str,
        slot: EquipmentSlot | None = None,
    ) -> EquipmentSlot:
        inventory = self._inventory(character)
        item = inventory.item(instance_id)
        template = self.catalog.get(item.template_id)
        if template.strength_requirement is not None:
            strength = character.attributes.get("Strength", 0)
            if strength < template.strength_requirement:
                raise InventoryError(
                    f"Requires Strength {template.strength_requirement}."
                )

        clear_off_hand = False
        if template.item_type is ItemType.WEAPON:
            if template.grip is WeaponGrip.TWO_HANDED:
                slot = EquipmentSlot.MAIN_HAND
                clear_off_hand = True
            elif slot is None:
                main_id = inventory.equipment.get(EquipmentSlot.MAIN_HAND)
                if main_id is not None:
                    main_template = self.catalog.get(inventory.item(main_id).template_id)
                    if main_template.grip is WeaponGrip.TWO_HANDED:
                        slot = EquipmentSlot.MAIN_HAND
                    else:
                        slot = EquipmentSlot.OFF_HAND
                else:
                    slot = EquipmentSlot.MAIN_HAND
            elif slot not in {EquipmentSlot.MAIN_HAND, EquipmentSlot.OFF_HAND}:
                raise InventoryError("Weapons require a hand slot.")
            if slot is EquipmentSlot.OFF_HAND:
                main_id = inventory.equipment.get(EquipmentSlot.MAIN_HAND)
                if main_id is not None and self.catalog.get(
                    inventory.item(main_id).template_id
                ).grip is WeaponGrip.TWO_HANDED:
                    raise InventoryError("Unequip the two-handed weapon first.")
        elif template.item_type is ItemType.ARMOR:
            slot = EquipmentSlot.ARMOR
        elif template.item_type is ItemType.CLOTHING:
            slot = EquipmentSlot.CLOTHING
        elif template.item_type is ItemType.CONTAINER and template.can_equip:
            slot = EquipmentSlot.CONTAINER
        else:
            raise InventoryError("That item cannot be equipped.")

        future_items = tuple(
            replace(candidate, parent_container_id=None)
            if candidate.instance_id == instance_id
            else candidate
            for candidate in inventory.items
        )
        future_equipment = dict(inventory.equipment)
        future_equipment = {
            equipped_slot: equipped_id
            for equipped_slot, equipped_id in future_equipment.items()
            if equipped_id != instance_id
        }
        future_equipment.pop(slot, None)
        if clear_off_hand:
            future_equipment.pop(EquipmentSlot.OFF_HAND, None)
        future_equipment[slot] = instance_id
        future = replace(
            inventory, items=future_items, equipment=future_equipment
        )
        if future.current_storage(self.catalog) > future.storage_capacity(self.catalog):
            raise InventoryError("There is not enough room to store displaced equipment.")
        self.database.equip_inventory_item(
            character.character_id,
            instance_id,
            slot,
            clear_off_hand=clear_off_hand,
        )
        return slot

    def unequip(self, character: Character, instance_id: str) -> None:
        inventory = self._inventory(character)
        slots = [
            slot for slot, equipped_id in inventory.equipment.items()
            if equipped_id == instance_id
        ]
        if not slots:
            raise InventoryError("That item is not equipped.")
        future_equipment = {
            slot: equipped_id
            for slot, equipped_id in inventory.equipment.items()
            if equipped_id != instance_id
        }
        future = replace(inventory, equipment=future_equipment)
        if future.current_storage(self.catalog) > future.storage_capacity(self.catalog):
            raise InventoryError("There is not enough inventory space to unequip that item.")
        for slot in slots:
            self.database.unequip_inventory_slot(character.character_id, slot)

    def use(self, character: Character, instance_id: str) -> Character:
        inventory = self._inventory(character)
        item = inventory.item(instance_id)
        template = self.catalog.get(item.template_id)
        if template.item_type is not ItemType.CONSUMABLE:
            raise InventoryError("That item is not consumable.")
        if template.affected_stat != "hp" or template.affected_amount is None:
            raise InventoryError("That consumable is not supported yet.")
        updated = self.database.heal(character.discord_user_id, template.affected_amount)
        self.database.set_inventory_item_quantity(
            character.character_id, instance_id, item.quantity - 1
        )
        return updated

    def _inventory(self, character: Character) -> InventoryState:
        if character.character_id is None:
            raise InventoryError("The character has not been saved.")
        return self.database.get_character_inventory(character.character_id)
