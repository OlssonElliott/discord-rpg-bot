"""State and result models for character creation."""

from dataclasses import dataclass, field
from enum import Enum


class CreationStep(str, Enum):
    LINEAGE = "lineage"
    RACE = "race"
    AGE = "age"
    GENDER = "gender"
    NAME = "name"
    ATTRIBUTES = "attributes"
    BONUS_POINTS = "bonus_points"
    SKILLS = "skills"
    COMPLETE = "complete"


class CharacterCreationValidationError(ValueError):
    """Raised when submitted input is invalid for the current creation step."""


@dataclass(frozen=True, slots=True)
class CharacterCreationResult:
    lineage: str
    race: str
    age: str
    gender: str
    name: str
    base_attributes: dict[str, int]
    bonus_points: dict[str, int]
    final_attributes: dict[str, int]
    skills: tuple[str, str]
    skill_ranks: dict[str, int]
    summary: str


@dataclass(slots=True)
class CharacterCreationState:
    step: CreationStep = CreationStep.LINEAGE
    lineage: str | None = None
    race: str | None = None
    age: str | None = None
    gender: str | None = None
    name: str | None = None
    base_attributes: dict[str, int] = field(default_factory=dict)
    bonus_points: dict[str, int] = field(default_factory=dict)
    final_attributes: dict[str, int] = field(default_factory=dict)
    skills: tuple[str, str] | None = None
    result: CharacterCreationResult | None = None
