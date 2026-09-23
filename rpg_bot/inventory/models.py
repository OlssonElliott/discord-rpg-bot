"""Inventory state models and recursive storage/weight measurements."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .catalog import ItemCatalog, ItemTemplate


DEFAULT_BASE_SLOTS = 4
DEFAULT_CARRY_CAPACITY = 10
DEFAULT_CLOTHING_TEMPLATE_ID = "common_clothing"
FREE_COIN_COUNT = 50
COINS_PER_WEIGHT = 50


class EquipmentSlot(str, Enum):
    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"
    CLOTHING = "clothing"
    ARMOR = "armor"
    CONTAINER = "container"


@dataclass(frozen=True, slots=True)
class ItemInstance:
    instance_id: str
    character_id: int
    template_id: str
    quantity: int = 1
    durability: int | None = None
    parent_container_id: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryState:
    character_id: int
    total_storage: int
    items: tuple[ItemInstance, ...]
    equipment: dict[EquipmentSlot, str]
    strength: int | None = None
    copper: int = 0
    silver: int = 0
    gold: int = 0

    def item(self, instance_id: str) -> ItemInstance:
        try:
            return next(item for item in self.items if item.instance_id == instance_id)
        except StopIteration as error:
            raise ValueError("That item is not in this inventory.") from error

    def current_storage(self, catalog: ItemCatalog) -> int:
        """Return slots occupied by unequipped item stacks."""
        equipped = set(self.equipment.values())
        return sum(
            catalog.get(item.template_id).slot_cost
            for item in self.items
            if item.instance_id not in equipped
        )

    def current_weight(self, catalog: ItemCatalog) -> int:
        item_weight = sum(
            (
                0
                if item.template_id == DEFAULT_CLOTHING_TEMPLATE_ID
                else catalog.get(item.template_id).weight * item.quantity
            )
            for item in self.items
        )
        return item_weight + self.coin_weight()

    def carry_capacity(self) -> int:
        return self.strength if self.strength is not None else DEFAULT_CARRY_CAPACITY

    def coin_count(self) -> int:
        return self.copper + self.silver + self.gold

    def coin_weight(self) -> int:
        weighted_coins = max(0, self.coin_count() - FREE_COIN_COUNT)
        return (weighted_coins + COINS_PER_WEIGHT - 1) // COINS_PER_WEIGHT

    def additional_slots(self, catalog: ItemCatalog, template: ItemTemplate) -> int:
        if template.stackable and any(
            item.template_id == template.template_id for item in self.items
        ):
            return 0
        return template.slot_cost

    def storage_capacity(self, catalog: ItemCatalog) -> int:
        """Return base storage plus the bonus from an equipped container."""
        container_id = self.equipment.get(EquipmentSlot.CONTAINER)
        if container_id is None:
            return self.total_storage
        template = catalog.get(self.item(container_id).template_id)
        return self.total_storage + (template.capacity or 0)
