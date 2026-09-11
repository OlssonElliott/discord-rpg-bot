"""Small domain models shared by the database and Discord commands."""

from dataclasses import dataclass, field
from enum import Enum


class Stance(str, Enum):
    STEADY = "steady"
    BAD_STANCE = "bad_stance"
    PRONE = "prone"

    @property
    def display_name(self) -> str:
        return self.value.replace("_", " ").title()


@dataclass(frozen=True, slots=True)
class Character:
    discord_user_id: int
    name: str
    hp: int
    max_hp: int
    stance: Stance
    lineage: str | None = None
    race: str | None = None
    age: str | None = None
    gender: str | None = None
    attributes: dict[str, int] = field(default_factory=dict)
    skills: dict[str, int] = field(default_factory=dict)
    character_id: int | None = None
    is_active: bool = True
    is_archived: bool = False
    portrait_key: str | None = None
    current_room_id: str | None = None


@dataclass(frozen=True, slots=True)
class CharacterSheetViewState:
    character_id: int
    guild_id: int
    discord_channel_id: int
    discord_message_id: int | None = None
