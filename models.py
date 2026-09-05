"""Small domain models shared by the database and Discord commands."""

from dataclasses import dataclass
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
