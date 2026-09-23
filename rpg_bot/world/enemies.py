"""Reusable enemy definitions and persistent enemy instance state."""

from dataclasses import dataclass
from enum import Enum


class EnemyStatus(str, Enum):
    ACTIVE = "active"
    DEAD = "dead"
    FLED = "fled"


@dataclass(frozen=True, slots=True)
class EnemyTemplate:
    template_id: str
    name: str
    description: str | None = None
    race: str = "Unknown"
    difficulty_level: int = 1
    strength: int = 0
    dexterity: int = 0
    arcana: int = 0
    vitality: int = 0
    insight: int = 0
    personality: int = 0
    max_hp: int = 7
    armor: int = 0
    magical_resistance: int = 0
    attack_dc: int = 12
    defense_dc: int = 12
    damage: str = "1d4"
    attack_profile: str = "Basic attack"
    special_ability: str | None = None
    typical_behaviour: str = "Unknown"
    main_hand_item_id: str | None = None
    off_hand_item_id: str | None = None
    armor_item_id: str | None = None

    def __post_init__(self) -> None:
        non_negative = {
            "difficulty level": self.difficulty_level,
            "strength": self.strength,
            "dexterity": self.dexterity,
            "arcana": self.arcana,
            "vitality": self.vitality,
            "insight": self.insight,
            "personality": self.personality,
            "armor": self.armor,
            "magical resistance": self.magical_resistance,
        }
        for label, value in non_negative.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"Enemy {label} must be a non-negative integer."
                )

        for label, value in {
            "max HP": self.max_hp,
            "attack DC": self.attack_dc,
            "defense DC": self.defense_dc,
        }.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(
                    f"Enemy {label} must be a positive integer."
                )

        for label, value in {
            "damage": self.damage,
            "attack profile": self.attack_profile,
            "typical behaviour": self.typical_behaviour,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Enemy {label} is required.")


@dataclass(frozen=True, slots=True)
class EnemyInstance:
    id: str
    room_id: str
    template_id: str
    name: str
    current_hp: int
    status: EnemyStatus = EnemyStatus.ACTIVE
    description: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.current_hp, bool)
            or not isinstance(self.current_hp, int)
            or self.current_hp < 0
        ):
            raise ValueError(
                "Enemy current HP must be a non-negative integer."
            )
