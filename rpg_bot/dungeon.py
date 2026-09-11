"""Player-specific dungeon knowledge and view domain models.

These types deliberately contain no Discord objects.  A player map is built from
persisted character knowledge first, then optionally transformed by perception
modifiers before it reaches a UI adapter.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class ConnectionType(str, Enum):
    DOOR = "door"
    PASSAGE = "passage"
    STAIRS_UP = "stairs_up"
    STAIRS_DOWN = "stairs_down"
    LADDER = "ladder"
    OPENING = "opening"


class KnowledgeState(str, Enum):
    UNKNOWN = "unknown"
    KNOWN = "known"
    VISITED = "visited"


class KnowledgeSource(str, Enum):
    DISCOVERED = "discovered"
    SHARED = "shared"


class GameLock(str, Enum):
    NONE = "none"
    MOVEMENT_LOCKED = "movement_locked"
    ALL_ACTIONS_LOCKED = "all_actions_locked"


@dataclass(frozen=True, slots=True)
class Floor:
    id: str
    dungeon_id: str
    floor_number: int
    name: str


@dataclass(frozen=True, slots=True)
class Dungeon:
    id: str
    name: str
    floors: tuple[Floor, ...] = ()


@dataclass(frozen=True, slots=True)
class RoomConnection:
    id: str
    from_room_id: str
    to_room_id: str
    connection_type: ConnectionType
    hidden: bool = False
    bidirectional: bool = False


@dataclass(frozen=True, slots=True)
class CharacterLocation:
    character_id: int
    room_id: str


@dataclass(frozen=True, slots=True)
class CharacterRoomKnowledge:
    character_id: int
    room_id: str
    state: KnowledgeState
    source: KnowledgeSource
    known_connection_ids: tuple[str, ...] = ()
    first_visited_at: datetime | None = None
    last_visited_at: datetime | None = None
    last_seen_scene_id: str | None = None
    shared_by_character_id: int | None = None


@dataclass(frozen=True, slots=True)
class PlayerViewState:
    character_id: int
    selected_floor_id: str | None = None
    focused_room_id: str | None = None
    discord_channel_id: int | None = None
    discord_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class PlayerMapRoom:
    id: str
    floor_id: str
    name: str
    x: float
    y: float
    width: float
    height: float
    knowledge_state: KnowledgeState
    is_current: bool = False
    is_focused: bool = False
    visible_characters: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        if self.knowledge_state is KnowledgeState.KNOWN:
            return f"? {self.name}"
        return self.name


@dataclass(frozen=True, slots=True)
class PlayerMapConnection:
    id: str
    from_room_id: str
    to_room_id: str
    from_floor_id: str
    to_floor_id: str
    connection_type: ConnectionType
    bidirectional: bool


@dataclass(frozen=True, slots=True)
class FocusedRoomView:
    room_id: str
    knowledge_state: KnowledgeState
    name: str
    description: str | None = None
    scene_image_path: str | None = None
    scene_image_url: str | None = None
    visible_characters: tuple[str, ...] = ()
    visible_entities: tuple[str, ...] = ()
    visible_items: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerMap:
    character_id: int
    dungeon_id: str
    floor: Floor
    current_room_id: str | None
    focused_room_id: str | None
    rooms: tuple[PlayerMapRoom, ...]
    connections: tuple[PlayerMapConnection, ...]
    focused_room: FocusedRoomView | None = None


class PerceptionModifier(Protocol):
    """Future illusion/effect boundary; implementations return a copied view."""

    def apply(self, view: PlayerMap) -> PlayerMap: ...


class PlayerViewMessageAdapter(Protocol):
    """Discord-facing boundary used to maintain one persistent bot message."""

    async def edit_view_message(
        self, channel_id: int, message_id: int, view: PlayerMap
    ) -> bool:
        """Return False when the stored message no longer exists."""

    async def create_view_message(self, channel_id: int, view: PlayerMap) -> int: ...
