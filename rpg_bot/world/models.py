"""Domain models for persisted areas, rooms, entities, and inventories."""

from dataclasses import dataclass
from enum import Enum

from .dungeon import ConnectionType, TrapDamageType, TrapState
from ..characters.models import Character


class EntityKind(str, Enum):
    ENEMY = "enemy"
    NPC = "npc"
    CONTAINER = "container"


class HolderKind(str, Enum):
    CHARACTER = "character"
    ROOM = "room"
    ENTITY = "entity"


@dataclass(frozen=True, slots=True)
class InventoryHolder:
    kind: HolderKind
    id: str

    @classmethod
    def character(cls, character_id: int) -> "InventoryHolder":
        return cls(HolderKind.CHARACTER, str(character_id))

    @classmethod
    def room(cls, room_id: str) -> "InventoryHolder":
        return cls(HolderKind.ROOM, room_id)

    @classmethod
    def entity(cls, entity_id: str) -> "InventoryHolder":
        return cls(HolderKind.ENTITY, entity_id)


@dataclass(frozen=True, slots=True)
class Area:
    id: str
    name: str
    description: str | None = None
    room_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Exit:
    name: str
    destination_room_id: str


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    description: str | None = None
    stackable: bool = True


@dataclass(frozen=True, slots=True)
class ItemStack:
    item: Item
    quantity: int


@dataclass(frozen=True, slots=True)
class WorldEntity:
    id: str
    room_id: str
    kind: EntityKind
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class Room:
    id: str
    area_id: str
    name: str
    description: str | None = None
    exits: tuple[Exit, ...] = ()
    entities: tuple[WorldEntity, ...] = ()
    characters: tuple[Character, ...] = ()
    loose_items: tuple[ItemStack, ...] = ()
    floor_id: str | None = None
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    scene_image_path: str | None = None
    scene_image_url: str | None = None
    scene_prompt: str | None = None

    @property
    def enemies(self) -> tuple[WorldEntity, ...]:
        return tuple(
            entity for entity in self.entities if entity.kind is EntityKind.ENEMY
        )

    @property
    def npcs(self) -> tuple[WorldEntity, ...]:
        return tuple(entity for entity in self.entities if entity.kind is EntityKind.NPC)

    @property
    def containers(self) -> tuple[WorldEntity, ...]:
        return tuple(
            entity for entity in self.entities if entity.kind is EntityKind.CONTAINER
        )


@dataclass(frozen=True, slots=True)
class MovementResult:
    room: Room
    trap_triggered: bool = False
    trap_damage: int = 0
    trap_damage_type: TrapDamageType | None = None


@dataclass(frozen=True, slots=True)
class RoomEditorNode:
    room: Room
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class GraphConnection:
    source_room_id: str
    exit_name: str
    destination_room_id: str
    connection_id: str | None = None
    return_exit_name: str | None = None
    bidirectional: bool = False
    hidden: bool = False
    connection_type: ConnectionType = ConnectionType.PASSAGE
    has_lock: bool = False
    is_locked: bool = False
    unlock_difficulty: int | None = None
    is_broken: bool = False
    is_open: bool = False
    has_trap: bool = False
    trap_state: TrapState | None = None
    trap_detection_difficulty: int | None = None
    trap_disarm_difficulty: int | None = None
    trap_damage_type: TrapDamageType | None = None
    trap_damage: int | None = None


@dataclass(frozen=True, slots=True)
class AreaGraph:
    area: Area
    nodes: tuple[RoomEditorNode, ...]
    connections: tuple[GraphConnection, ...]


class WorldError(ValueError):
    """Base class for deterministic world-rule failures."""


class NotFoundError(WorldError):
    pass


class InvalidMovementError(WorldError):
    pass


class InvalidTransferError(WorldError):
    pass
