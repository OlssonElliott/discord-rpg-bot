"""Inventory domain models, item catalog loading, and recursive measurements."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Iterable


class ItemType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    CONTAINER = "container"
    CONSUMABLE = "consumable"
    MISC = "misc"


class WeaponGrip(str, Enum):
    ONE_HANDED = "one_handed"
    TWO_HANDED = "two_handed"


class EquipmentSlot(str, Enum):
    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"
    ARMOR = "armor"
    CONTAINER = "container"


@dataclass(frozen=True, slots=True)
class DamagePart:
    amount: int
    damage_type: str


@dataclass(frozen=True, slots=True)
class ItemTemplate:
    template_id: str
    item_type: ItemType
    name: str
    rarity: str
    value: int
    description: str
    weight: int
    tags: tuple[str, ...] = ()
    grip: WeaponGrip | None = None
    durability: int | None = None
    damage_parts: tuple[DamagePart, ...] = ()
    protection: int | None = None
    dodge_penalty: int = 0
    strength_requirement: int | None = None
    capacity: int | None = None
    can_equip: bool = False
    affected_stat: str | None = None
    affected_amount: int | None = None
    trait: str | None = None
    drawback: str | None = None

    @property
    def stackable(self) -> bool:
        return self.item_type is ItemType.CONSUMABLE


@dataclass(frozen=True, slots=True)
class ItemInstance:
    instance_id: str
    character_id: int
    template_id: str
    quantity: int = 1
    durability: int | None = None
    parent_container_id: str | None = None


class ItemCatalog:
    def __init__(self, templates: Iterable[ItemTemplate]) -> None:
        self._templates = {template.template_id: template for template in templates}

    @classmethod
    def load(cls, path: str | Path) -> ItemCatalog:
        with Path(path).open("r", encoding="utf-8") as file:
            records = json.load(file)
        if not isinstance(records, list):
            raise ValueError("Item catalog must contain a JSON list.")
        return cls(cls._template_from_record(record) for record in records)

    @staticmethod
    def _template_from_record(record: dict[str, object]) -> ItemTemplate:
        item_type = ItemType(str(record["item_type"]))
        protection = int(record.get("protection_max", record.get("protection", 0)))
        return ItemTemplate(
            template_id=str(record["id"]),
            item_type=item_type,
            name=str(record["name"]),
            rarity=str(record["rarity"]),
            value=int(record["value"]),
            description=str(record["description"]),
            weight=int(record.get("weight", record.get("load", 0))),
            tags=tuple(str(tag) for tag in record.get("tags", [])),
            grip=(
                WeaponGrip(str(record.get("grip", "one_handed")))
                if item_type is ItemType.WEAPON
                else None
            ),
            durability=(
                int(record["durability"])
                if item_type is ItemType.WEAPON
                else protection
                if item_type is ItemType.ARMOR
                else None
            ),
            damage_parts=tuple(
                DamagePart(int(part["amount"]), str(part["damage_type"]))
                for part in record.get("damage_parts", [])
            ),
            protection=protection if item_type is ItemType.ARMOR else None,
            dodge_penalty=int(record.get("dodge_penalty", 0)),
            strength_requirement=(
                int(record["strength_requirement"])
                if record.get("strength_requirement") is not None
                else None
            ),
            capacity=(
                int(record.get("capacity", 0))
                if item_type is ItemType.CONTAINER
                else None
            ),
            can_equip=bool(record.get("can_equip", False)),
            affected_stat=(
                str(record["affected_stat"])
                if record.get("affected_stat") is not None
                else None
            ),
            affected_amount=(
                int(record["affected_amount"])
                if record.get("affected_amount") is not None
                else None
            ),
            trait=str(record["trait"]) if record.get("trait") else None,
            drawback=str(record["drawback"]) if record.get("drawback") else None,
        )

    def get(self, template_id: str) -> ItemTemplate:
        try:
            return self._templates[template_id]
        except KeyError as error:
            raise ValueError(f"Unknown item template: {template_id}") from error

    def all(self) -> tuple[ItemTemplate, ...]:
        return tuple(self._templates.values())


@dataclass(frozen=True, slots=True)
class InventoryState:
    character_id: int
    total_storage: int
    items: tuple[ItemInstance, ...]
    equipment: dict[EquipmentSlot, str]

    def item(self, instance_id: str) -> ItemInstance:
        try:
            return next(item for item in self.items if item.instance_id == instance_id)
        except StopIteration as error:
            raise ValueError("That item is not in this inventory.") from error

    def children_of(self, parent_id: str | None) -> tuple[ItemInstance, ...]:
        return tuple(
            item for item in self.items if item.parent_container_id == parent_id
        )

    def recursive_weight(
        self,
        instance_id: str,
        catalog: ItemCatalog,
        ancestors: frozenset[str] = frozenset(),
    ) -> int:
        if instance_id in ancestors:
            raise ValueError("Inventory contains a container cycle.")
        item = self.item(instance_id)
        template = catalog.get(item.template_id)
        own_weight = template.weight * item.quantity
        descendants = sum(
            self.recursive_weight(
                child.instance_id, catalog, ancestors | {instance_id}
            )
            for child in self.children_of(instance_id)
        )
        return own_weight + descendants

    def container_storage(self, instance_id: str, catalog: ItemCatalog) -> int:
        return sum(
            self.recursive_weight(child.instance_id, catalog)
            for child in self.children_of(instance_id)
        )

    def current_storage(self, catalog: ItemCatalog) -> int:
        equipped = set(self.equipment.values())
        return sum(
            self.recursive_weight(item.instance_id, catalog)
            for item in self.children_of(None)
            if item.instance_id not in equipped
        )

    def current_weight(self, catalog: ItemCatalog) -> int:
        return sum(
            self.recursive_weight(item.instance_id, catalog)
            for item in self.children_of(None)
        )

    def contains(self, container_id: str, possible_descendant_id: str) -> bool:
        return any(
            child.instance_id == possible_descendant_id
            or self.contains(child.instance_id, possible_descendant_id)
            for child in self.children_of(container_id)
        )


DEFAULT_ITEM_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "items" / "items.json"
)
