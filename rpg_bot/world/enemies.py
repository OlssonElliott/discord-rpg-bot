"""Reusable enemy definitions and persistent enemy instance state."""

from dataclasses import dataclass
from enum import Enum
import re


class EnemyStatus(str, Enum):
    ACTIVE = "active"
    DEAD = "dead"
    FLED = "fled"


class EnemyCombatRole(str, Enum):
    MELEE = "melee"
    RANGED = "ranged"
    SPELLCASTER = "spellcaster"


@dataclass(frozen=True, slots=True)
class EnemyNaturalAttack:
    name: str
    damage: str
    damage_type: str = "physical"
    range: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Natural attack name is required.")
        if not self.damage.strip():
            raise ValueError("Natural attack damage is required.")
        if not re.fullmatch(
            r"\d+d\d+(?:\s*\+\s*\d+d\d+)*",
            self.damage.strip(),
            flags=re.IGNORECASE,
        ):
            raise ValueError(
                "Natural attack damage must use dice notation such as 1d6."
            )
        if not self.damage_type.strip():
            raise ValueError("Natural attack damage type is required.")
        if isinstance(self.range, bool) or not isinstance(self.range, int) or self.range < 0:
            raise ValueError("Natural attack range must be a non-negative integer.")


@dataclass(frozen=True, slots=True)
class EnemyTemplate:
    template_id: str
    name: str
    description: str | None = None
    race: str = "Unknown"
    lineage: str = "Other"
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
    melee_weapon_ids: tuple[str, ...] = ()
    ranged_weapon_ids: tuple[str, ...] = ()
    off_hand_item_ids: tuple[str, ...] = ()
    armor_item_ids: tuple[str, ...] = ()
    spell_names: tuple[str, ...] = ()
    spell_range: int = 3
    melee_damage_filter: str | None = None
    ranged_damage_filter: str | None = None
    natural_attacks: tuple[EnemyNaturalAttack, ...] = ()
    armor_reduction_filter: int | None = None
    dual_wield: bool = False
    allowed_races: tuple[str, ...] = ()
    melee_loadouts: tuple[str, ...] = ()
    shield_item_ids: tuple[str, ...] = ()

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
            "spell range": self.spell_range,
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

        if (
            self.armor_reduction_filter is not None
            and (
                isinstance(self.armor_reduction_filter, bool)
                or not isinstance(self.armor_reduction_filter, int)
                or self.armor_reduction_filter < 0
            )
        ):
            raise ValueError(
                "Enemy armor reduction filter must be a non-negative integer."
            )
        if not isinstance(self.dual_wield, bool):
            raise ValueError("Enemy dual wield setting must be boolean.")

        for label, value in {
            "melee damage filter": self.melee_damage_filter,
            "ranged damage filter": self.ranged_damage_filter,
        }.items():
            if value is not None and not value.strip():
                raise ValueError(f"Enemy {label} cannot be empty.")

        valid_melee_loadouts = {
            "one_handed",
            "shield",
            "dual_wield",
            "two_handed",
            "natural",
        }
        if any(
            loadout not in valid_melee_loadouts
            for loadout in self.melee_loadouts
        ):
            raise ValueError(
                "Enemy melee loadouts contain an unknown configuration."
            )

        natural_attack_names = [
            attack.name.casefold()
            for attack in self.natural_attacks
        ]
        if len(natural_attack_names) != len(set(natural_attack_names)):
            raise ValueError("Natural attack names cannot contain duplicates.")

        for label, values in {
            "melee weapon pool": self.melee_weapon_ids,
            "ranged weapon pool": self.ranged_weapon_ids,
            "off-hand pool": self.off_hand_item_ids,
            "armor pool": self.armor_item_ids,
            "shield pool": self.shield_item_ids,
            "allowed races": self.allowed_races,
            "melee loadouts": self.melee_loadouts,
            "spell access": self.spell_names,
        }.items():
            if len(values) != len(set(values)):
                raise ValueError(f"Enemy {label} cannot contain duplicates.")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValueError(f"Enemy {label} values must be non-empty text.")


@dataclass(frozen=True, slots=True)
class EnemyInstance:
    id: str
    room_id: str
    template_id: str
    name: str
    current_hp: int
    status: EnemyStatus = EnemyStatus.ACTIVE
    description: str | None = None
    combat_role: EnemyCombatRole = EnemyCombatRole.MELEE
    main_hand_item_id: str | None = None
    off_hand_item_id: str | None = None
    armor_item_id: str | None = None
    selected_spell: str | None = None
    selected_natural_attack: EnemyNaturalAttack | None = None
    race: str = "Unknown"
    loadout_style: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.current_hp, bool)
            or not isinstance(self.current_hp, int)
            or self.current_hp < 0
        ):
            raise ValueError(
                "Enemy current HP must be a non-negative integer."
            )
