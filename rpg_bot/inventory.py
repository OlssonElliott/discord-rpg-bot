"""Inventory domain models, item catalog loading, and recursive measurements."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import threading
from typing import Iterable
from uuid import uuid4


DEFAULT_BASE_SLOTS = 4
DEFAULT_CARRY_CAPACITY = 10
DEFAULT_CLOTHING_TEMPLATE_ID = "common_clothing"
FREE_COIN_COUNT = 50
COINS_PER_WEIGHT = 50


class ItemType(str, Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    CLOTHING = "clothing"
    CONTAINER = "container"
    CONSUMABLE = "consumable"
    READABLE = "readable"
    MISC = "misc"


class WeaponGrip(str, Enum):
    ONE_HANDED = "one_handed"
    TWO_HANDED = "two_handed"


class EquipmentSlot(str, Enum):
    MAIN_HAND = "main_hand"
    OFF_HAND = "off_hand"
    CLOTHING = "clothing"
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
    slot_cost: int | None = None
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
    content: str | None = None

    def __post_init__(self) -> None:
        if self.weight < 0:
            raise ValueError("Item weight cannot be negative.")
        if self.slot_cost is None:
            object.__setattr__(
                self,
                "slot_cost",
                0 if self.item_type is ItemType.READABLE and self.weight == 0 else 1,
            )
        elif self.slot_cost < 0:
            raise ValueError("Item slot cost cannot be negative.")

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
    def __init__(
        self,
        templates: Iterable[ItemTemplate],
        *,
        source_path: Path | None = None,
        records: list[dict[str, object]] | None = None,
    ) -> None:
        self._templates = {template.template_id: template for template in templates}
        self._source_path = source_path
        self._records = records
        self._source_signature = self._signature()
        self._lock = threading.RLock()

    @classmethod
    def load(cls, path: str | Path) -> ItemCatalog:
        source_path = Path(path)
        with source_path.open("r", encoding="utf-8") as file:
            records = json.load(file)
        if not isinstance(records, list):
            raise ValueError("Item catalog must contain a JSON list.")
        return cls(
            (cls._template_from_record(record) for record in records),
            source_path=source_path,
            records=records,
        )

    @staticmethod
    def _template_from_record(record: dict[str, object]) -> ItemTemplate:
        item_type = ItemType(str(record["item_type"]))
        protection = int(record.get("protection_max", record.get("protection", 0)))
        weight = int(record.get("weight", record.get("load", 0)))
        slot_cost = int(
            record.get(
                "slot_cost",
                0 if item_type is ItemType.READABLE and weight == 0 else 1,
            )
        )
        if weight < 0 or slot_cost < 0:
            raise ValueError("Item weight and slot cost cannot be negative.")
        return ItemTemplate(
            template_id=str(record["id"]),
            item_type=item_type,
            name=str(record["name"]),
            rarity=str(record["rarity"]),
            value=int(record["value"]),
            description=str(record["description"]),
            weight=weight,
            slot_cost=slot_cost,
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
            content=(
                str(record.get("content", ""))
                if item_type is ItemType.READABLE
                else None
            ),
        )

    def get(self, template_id: str) -> ItemTemplate:
        self._reload_if_changed()
        try:
            return self._templates[template_id]
        except KeyError as error:
            raise ValueError(f"Unknown item template: {template_id}") from error

    def all(self) -> tuple[ItemTemplate, ...]:
        self._reload_if_changed()
        return tuple(self._templates.values())

    def create(self, record: dict[str, object]) -> ItemTemplate:
        """Validate and persist a new template in the shared JSON catalog."""
        template = self._template_from_record(record)
        with self._lock:
            self._reload_if_changed()
            if template.template_id in self._templates:
                raise ValueError(f"Item template '{template.template_id}' already exists.")
            if any(
                existing.name.casefold() == template.name.casefold()
                for existing in self._templates.values()
            ):
                raise ValueError(f"An item named '{template.name}' already exists.")
            if self._source_path is None or self._records is None:
                raise ValueError("This item catalog is not backed by a writable file.")

            records = [*self._records, record]
            self._write_records(records)
            self._records = records
            self._templates[template.template_id] = template
            self._source_signature = self._signature()
        return template

    def update(
        self, template_id: str, record: dict[str, object]
    ) -> ItemTemplate:
        """Replace a template while keeping its stable catalog identifier."""
        updated_record = {**record, "id": template_id}
        template = self._template_from_record(updated_record)
        with self._lock:
            self._reload_if_changed()
            if template_id not in self._templates:
                raise ValueError(f"Unknown item template: {template_id}")
            if self._templates[template_id].item_type is not template.item_type:
                raise ValueError("An existing item's type cannot be changed.")
            if any(
                existing.template_id != template_id
                and existing.name.casefold() == template.name.casefold()
                for existing in self._templates.values()
            ):
                raise ValueError(f"An item named '{template.name}' already exists.")
            if self._source_path is None or self._records is None:
                raise ValueError("This item catalog is not backed by a writable file.")
            records = [
                updated_record if str(candidate.get("id")) == template_id else candidate
                for candidate in self._records
            ]
            self._write_records(records)
            self._records = records
            self._templates[template_id] = template
            self._source_signature = self._signature()
        return template

    def _write_records(self, records: list[dict[str, object]]) -> None:
        if self._source_path is None:
            raise ValueError("This item catalog is not backed by a writable file.")
        temporary = self._source_path.with_name(
            f".{self._source_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(records, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._source_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _reload_if_changed(self) -> None:
        if self._source_path is None:
            return
        current_signature = self._signature()
        if current_signature == self._source_signature:
            return
        with self._lock:
            current_signature = self._signature()
            if current_signature == self._source_signature:
                return
            with self._source_path.open("r", encoding="utf-8") as file:
                records = json.load(file)
            if not isinstance(records, list):
                raise ValueError("Item catalog must contain a JSON list.")
            templates = [self._template_from_record(record) for record in records]
            self._templates = {
                template.template_id: template for template in templates
            }
            self._records = records
            self._source_signature = current_signature

    def _signature(self) -> tuple[int, int, int] | None:
        if self._source_path is None:
            return None
        try:
            stat = self._source_path.stat()
            return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        except OSError:
            return None


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

DEFAULT_ITEM_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "items" / "items.json"
)
