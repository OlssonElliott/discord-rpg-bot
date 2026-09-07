"""Canonical character creation rules and validation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from .models import CharacterCreationValidationError


ATTRIBUTES = (
    "Strength",
    "Dexterity",
    "Arcana",
    "Vitality",
    "Insight",
    "Personality",
)
STANDARD_ARRAY = (14, 13, 12, 11, 10, 9)
LINEAGES = ("Commonfolk", "Fey", "Primals", "Felblood", "Wretched")
RACES_BY_LINEAGE = {
    "Commonfolk": ("Human", "Dwarf", "Halfling"),
    "Fey": ("Elf", "Dryad", "Faun"),
    "Primals": ("Gnoll", "Lizardman", "Minotaur"),
    "Felblood": ("Orc", "Troll", "Goblin"),
    "Wretched": ("Revenant", "Hagspawn", "Swarmling"),
}
AGES = ("Young", "Prime", "Old")
GENDERS = ("Male", "Female")
SKILL_TREES = (
    "Melee",
    "Ranged",
    "Spellcasting",
    "Stealth",
    "Survival",
    "Crafting",
    "Guile",
)
RACE_MODIFIERS = {
    "Human": {"Personality": 1, "Insight": 1},
    "Dwarf": {"Vitality": 1, "Strength": 1},
    "Halfling": {"Dexterity": 1, "Personality": 1},
    "Elf": {"Arcana": 1, "Dexterity": 1},
    "Dryad": {"Arcana": 2},
    "Faun": {"Dexterity": 1, "Insight": 1},
    "Gnoll": {"Strength": 2},
    "Lizardman": {"Vitality": 1, "Insight": 1},
    "Minotaur": {"Strength": 2},
    "Orc": {"Strength": 1, "Vitality": 1},
    "Troll": {"Vitality": 2},
    "Goblin": {"Dexterity": 2},
    "Revenant": {"Vitality": 1, "Arcana": 1},
    "Hagspawn": {"Arcana": 2},
    "Swarmling": {"Dexterity": 1, "Insight": 1},
}
AGE_MODIFIERS = {
    "Young": {"Dexterity": 1, "Insight": -1},
    "Prime": {"Personality": 1},
    "Old": {"Insight": 1, "Strength": -1},
}

_LINEAGE_ALIASES = {"common": "Commonfolk", "primal": "Primals", "fel": "Felblood"}
_GENDER_ALIASES = {"man": "Male", "woman": "Female"}
_ATTRIBUTE_ALIASES = {
    "strength": "Strength",
    "strenght": "Strength",
    "str": "Strength",
    "dexterity": "Dexterity",
    "dex": "Dexterity",
    "arcana": "Arcana",
    "vitality": "Vitality",
    "vit": "Vitality",
    "insight": "Insight",
    "ingisht": "Insight",
    "insigth": "Insight",
    "insite": "Insight",
    "personality": "Personality",
    "per": "Personality",
}
_PAIR_PATTERN = re.compile(r"([A-Za-z]+)\s*(?:\+|:|=|\s)\s*(-?\d+)")


def canonical_choice(
    value: object,
    choices: Sequence[str],
    *,
    aliases: Mapping[str, str] | None = None,
) -> str:
    answer = str(value).strip().casefold()
    if not answer:
        raise CharacterCreationValidationError("A choice is required.")
    if answer.isdigit():
        index = int(answer) - 1
        if 0 <= index < len(choices):
            return choices[index]
    for choice in choices:
        if answer == choice.casefold():
            return choice
    if aliases and answer in aliases:
        candidate = aliases[answer]
        if candidate in choices:
            return candidate
    raise CharacterCreationValidationError(
        f"Choose one of: {', '.join(choices)}."
    )


def parse_lineage(value: object) -> str:
    return canonical_choice(value, LINEAGES, aliases=_LINEAGE_ALIASES)


def parse_race(value: object, lineage: str) -> str:
    races = RACES_BY_LINEAGE[lineage]
    try:
        return canonical_choice(value, races)
    except CharacterCreationValidationError as error:
        raise CharacterCreationValidationError(
            f"Choose a {lineage} race: {', '.join(races)}."
        ) from error


def genders_for_race(race: str | None) -> tuple[str, ...]:
    if race == "Dryad":
        return ("Female",)
    if race == "Faun":
        return ("Male",)
    return GENDERS


def parse_gender(value: object, race: str) -> str:
    return canonical_choice(value, genders_for_race(race), aliases=_GENDER_ALIASES)


def parse_name(value: object) -> str:
    name = " ".join(str(value).strip().split())
    if not name:
        raise CharacterCreationValidationError("Enter a character name.")
    if len(name) > 100:
        raise CharacterCreationValidationError(
            "Character name cannot be longer than 100 characters."
        )
    return name


def _attribute_mapping(value: object) -> dict[str, int]:
    if isinstance(value, Mapping):
        pairs = list(value.items())
    else:
        text = str(value)
        matches = _PAIR_PATTERN.findall(text)
        if matches:
            pairs = matches
        else:
            numbers = [int(token) for token in re.findall(r"-?\d+", text)]
            if len(numbers) != len(ATTRIBUTES):
                raise CharacterCreationValidationError(
                    "Provide a value for every attribute."
                )
            return dict(zip(ATTRIBUTES, numbers))

    parsed: dict[str, int] = {}
    for raw_name, raw_value in pairs:
        canonical = _ATTRIBUTE_ALIASES.get(str(raw_name).strip().casefold())
        if canonical is None:
            raise CharacterCreationValidationError(
                f"Unknown attribute: {raw_name}."
            )
        if canonical in parsed:
            raise CharacterCreationValidationError(
                f"Attribute supplied more than once: {canonical}."
            )
        try:
            parsed[canonical] = int(raw_value)
        except (TypeError, ValueError) as error:
            raise CharacterCreationValidationError(
                f"{canonical} must be a whole number."
            ) from error
    return parsed


def parse_attributes(value: object) -> dict[str, int]:
    attributes = _attribute_mapping(value)
    if set(attributes) != set(ATTRIBUTES):
        raise CharacterCreationValidationError(
            "All six attributes are required with no extras."
        )
    if sorted(attributes.values(), reverse=True) != list(STANDARD_ARRAY):
        raise CharacterCreationValidationError(
            "Use every standard-array value exactly once: 14, 13, 12, 11, 10, 9."
        )
    return {attribute: attributes[attribute] for attribute in ATTRIBUTES}


def parse_bonus_points(value: object) -> dict[str, int]:
    points = _attribute_mapping(value)
    if not points:
        raise CharacterCreationValidationError("Assign exactly 2 bonus points.")
    if any(amount < 0 for amount in points.values()):
        raise CharacterCreationValidationError("Bonus points cannot be negative.")
    if sum(points.values()) != 2:
        raise CharacterCreationValidationError("Assign exactly 2 bonus points.")
    return points


def parse_skills(value: object) -> tuple[str, str]:
    if isinstance(value, str):
        raw_values = [part for part in re.split(r"[,;/]|\s+", value.strip()) if part]
    elif isinstance(value, Sequence):
        raw_values = list(value)
    else:
        raise CharacterCreationValidationError("Choose exactly two skill trees.")
    if len(raw_values) != 2:
        raise CharacterCreationValidationError("Choose exactly two skill trees.")
    skills = tuple(canonical_choice(item, SKILL_TREES) for item in raw_values)
    if skills[0] == skills[1]:
        raise CharacterCreationValidationError("Choose two different skill trees.")
    return skills


def apply_modifiers(
    base: Mapping[str, int],
    bonus: Mapping[str, int],
    race: str,
    age: str,
) -> dict[str, int]:
    values = dict(base)
    for modifiers in (bonus, RACE_MODIFIERS[race], AGE_MODIFIERS[age]):
        for attribute, amount in modifiers.items():
            values[attribute] += amount
    return {
        attribute: max(8, min(16, values[attribute]))
        for attribute in ATTRIBUTES
    }
