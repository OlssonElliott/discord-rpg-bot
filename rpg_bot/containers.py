"""Reusable loot-container templates and placed world-container state."""

from dataclasses import dataclass
from enum import Enum


class ContainerType(str, Enum):
    WOODEN_CHEST = "wooden_chest"
    REINFORCED_CHEST = "reinforced_chest"
    BARREL = "barrel"
    CRATE = "crate"
    SHELF = "shelf"
    BOOKSHELF = "bookshelf"
    CORPSE = "corpse"
    SKELETON = "skeleton"
    BACKPACK = "backpack"
    HIDDEN_COMPARTMENT = "hidden_compartment"
    LOOSE_FLOORBOARD = "loose_floorboard"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ContainerTemplate:
    template_id: str
    name: str
    container_type: ContainerType
    description: str | None = None
    default_has_lock: bool = False
    default_is_locked: bool = False
    default_is_broken: bool = False
    default_unlock_difficulty: int | None = None
    default_hidden: bool = False
    default_discovery_difficulty: int | None = None


@dataclass(frozen=True, slots=True)
class ContainerInstance:
    id: str
    room_id: str
    template_id: str
    name: str
    container_type: ContainerType
    description: str | None = None
    has_lock: bool = False
    is_locked: bool = False
    is_broken: bool = False
    unlock_difficulty: int | None = None
    hidden: bool = False
    discovery_difficulty: int | None = None
    is_open: bool = False
    searched: bool = False
