"""Deterministic character creation state machine."""

from __future__ import annotations

from .models import (
    CharacterCreationResult,
    CharacterCreationState,
    CharacterCreationValidationError,
    CreationStep,
)
from .rules import (
    AGES,
    ATTRIBUTES,
    LINEAGES,
    RACES_BY_LINEAGE,
    SKILL_TREES,
    apply_modifiers,
    canonical_choice,
    genders_for_race,
    parse_attributes,
    parse_bonus_points,
    parse_gender,
    parse_lineage,
    parse_name,
    parse_race,
    parse_skills,
)


class CharacterCreationFlow:
    """Accepts one validated choice at a time without any Discord coupling."""

    def __init__(self) -> None:
        self.state = CharacterCreationState()

    @property
    def current_step(self) -> CreationStep:
        return self.state.step

    @property
    def result(self) -> CharacterCreationResult | None:
        return self.state.result

    def reset(self) -> None:
        self.state = CharacterCreationState()

    def valid_choices(self) -> tuple[str, ...]:
        if self.current_step is CreationStep.LINEAGE:
            return LINEAGES
        if self.current_step is CreationStep.RACE and self.state.lineage:
            return RACES_BY_LINEAGE[self.state.lineage]
        if self.current_step is CreationStep.AGE:
            return AGES
        if self.current_step is CreationStep.GENDER:
            return genders_for_race(self.state.race)
        if self.current_step is CreationStep.ATTRIBUTES:
            return ATTRIBUTES
        if self.current_step is CreationStep.SKILLS:
            return SKILL_TREES
        return ()

    def submit(self, value: object) -> CreationStep:
        """Validate and apply input, returning the next step.

        Validation is completed before state mutation, so rejected input never
        advances or partially changes the flow.
        """
        step = self.current_step
        state = self.state
        if step is CreationStep.COMPLETE:
            raise CharacterCreationValidationError(
                "Character creation is already complete."
            )

        if step is CreationStep.LINEAGE:
            accepted = parse_lineage(value)
            state.lineage = accepted
            state.step = CreationStep.RACE
        elif step is CreationStep.RACE:
            accepted = parse_race(value, self._required(state.lineage, "lineage"))
            state.race = accepted
            state.step = CreationStep.AGE
        elif step is CreationStep.AGE:
            accepted = canonical_choice(value, AGES)
            state.age = accepted
            state.step = CreationStep.GENDER
        elif step is CreationStep.GENDER:
            accepted = parse_gender(value, self._required(state.race, "race"))
            state.gender = accepted
            state.step = CreationStep.NAME
        elif step is CreationStep.NAME:
            accepted = parse_name(value)
            state.name = accepted
            state.step = CreationStep.ATTRIBUTES
        elif step is CreationStep.ATTRIBUTES:
            accepted = parse_attributes(value)
            state.base_attributes = accepted
            state.step = CreationStep.BONUS_POINTS
        elif step is CreationStep.BONUS_POINTS:
            accepted = parse_bonus_points(value)
            final = apply_modifiers(
                state.base_attributes,
                accepted,
                self._required(state.race, "race"),
                self._required(state.age, "age"),
            )
            state.bonus_points = accepted
            state.final_attributes = final
            state.step = CreationStep.SKILLS
        else:
            accepted = parse_skills(value)
            state.skills = accepted
            state.result = self._build_result()
            state.step = CreationStep.COMPLETE
        return state.step

    @staticmethod
    def _required(value: str | None, field: str) -> str:
        if value is None:
            raise RuntimeError(f"Character creation state is missing {field}.")
        return value

    def _build_result(self) -> CharacterCreationResult:
        state = self.state
        skills = state.skills
        if skills is None:
            raise RuntimeError("Character creation state is missing skills.")
        name = self._required(state.name, "name")
        lineage = self._required(state.lineage, "lineage")
        race = self._required(state.race, "race")
        age = self._required(state.age, "age")
        gender = self._required(state.gender, "gender")
        attributes = ", ".join(
            f"{attribute} {state.final_attributes[attribute]}"
            for attribute in ATTRIBUTES
        )
        summary = (
            f"{name}, {lineage} {race} ({age}, {gender}) with "
            f"{', '.join(skills)} at Rank 1. Final attributes: {attributes}."
        )
        return CharacterCreationResult(
            lineage=lineage,
            race=race,
            age=age,
            gender=gender,
            name=name,
            base_attributes=dict(state.base_attributes),
            bonus_points=dict(state.bonus_points),
            final_attributes=dict(state.final_attributes),
            skills=skills,
            skill_ranks={skill: 1 for skill in skills},
            summary=summary,
        )
