import tempfile
import unittest
from pathlib import Path

from rpg_bot.character_creation import (
    CharacterCreationFlow,
    CharacterCreationValidationError,
    CreationStep,
)
from rpg_bot.character_creation.rules import (
    AGES,
    ATTRIBUTES,
    LINEAGES,
    RACES_BY_LINEAGE,
    AGE_MODIFIERS,
    RACE_MODIFIERS,
    apply_modifiers,
    parse_attributes,
    parse_bonus_points,
    parse_gender,
    parse_lineage,
    parse_name,
    parse_race,
    parse_skills,
)
from rpg_bot.character_creation.service import CharacterCreationService
from rpg_bot.database import CharacterAlreadyExistsError, Database


VALID_ATTRIBUTES = {
    "Strength": 14,
    "Dexterity": 13,
    "Arcana": 12,
    "Vitality": 11,
    "Insight": 10,
    "Personality": 9,
}


def completed_flow(
    *, race: str = "Human", age: str = "Prime"
) -> CharacterCreationFlow:
    lineage = next(
        lineage
        for lineage, races in RACES_BY_LINEAGE.items()
        if race in races
    )
    flow = CharacterCreationFlow()
    for answer in (
        lineage,
        race,
        age,
        "Female",
        "Aria",
        VALID_ATTRIBUTES,
        {"Strength": 1, "Arcana": 1},
        ("Melee", "Survival"),
    ):
        flow.submit(answer)
    return flow


class CharacterCreationRuleTests(unittest.TestCase):
    def test_every_lineage_and_race_mapping(self) -> None:
        self.assertEqual(tuple(RACES_BY_LINEAGE), LINEAGES)
        for lineage, races in RACES_BY_LINEAGE.items():
            self.assertEqual(parse_lineage(lineage.lower()), lineage)
            for race in races:
                self.assertEqual(parse_race(race.lower(), lineage), race)

    def test_invalid_lineage_race_and_wrong_lineage_are_rejected(self) -> None:
        with self.assertRaises(CharacterCreationValidationError):
            parse_lineage("Martian")
        with self.assertRaises(CharacterCreationValidationError):
            parse_race("Dragon", "Fey")
        with self.assertRaises(CharacterCreationValidationError):
            parse_race("Human", "Fey")

    def test_all_age_selections(self) -> None:
        for age in AGES:
            flow = CharacterCreationFlow()
            flow.submit("Commonfolk")
            flow.submit("Human")
            flow.submit(age.lower())
            self.assertEqual(flow.state.age, age)

    def test_gender_rules(self) -> None:
        self.assertEqual(parse_gender("female", "Dryad"), "Female")
        self.assertEqual(parse_gender("male", "Faun"), "Male")
        self.assertEqual(parse_gender("woman", "Human"), "Female")
        self.assertEqual(parse_gender("man", "Human"), "Male")
        with self.assertRaises(CharacterCreationValidationError):
            parse_gender("Male", "Dryad")
        with self.assertRaises(CharacterCreationValidationError):
            parse_gender("Female", "Faun")

    def test_name_is_required(self) -> None:
        self.assertEqual(parse_name("  Aria   Storm  "), "Aria Storm")
        with self.assertRaises(CharacterCreationValidationError):
            parse_name("   ")

    def test_standard_array_requires_all_values_exactly_once(self) -> None:
        self.assertEqual(parse_attributes(VALID_ATTRIBUTES), VALID_ATTRIBUTES)
        self.assertEqual(
            parse_attributes("14 13 12 11 10 9"), VALID_ATTRIBUTES
        )
        invalid_values = dict(VALID_ATTRIBUTES, Personality=10)
        with self.assertRaises(CharacterCreationValidationError):
            parse_attributes(invalid_values)
        missing = dict(VALID_ATTRIBUTES)
        missing.pop("Insight")
        with self.assertRaises(CharacterCreationValidationError):
            parse_attributes(missing)
        extra = dict(VALID_ATTRIBUTES, Luck=8)
        with self.assertRaises(CharacterCreationValidationError):
            parse_attributes(extra)
        with self.assertRaises(CharacterCreationValidationError):
            parse_attributes(
                "Strength 14, Strength 13, Arcana 12, Vitality 11, "
                "Insight 10, Personality 9"
            )

    def test_bonus_points_require_exactly_two_nonnegative_points(self) -> None:
        self.assertEqual(
            parse_bonus_points({"Strength": 1, "Arcana": 1}),
            {"Strength": 1, "Arcana": 1},
        )
        self.assertEqual(parse_bonus_points({"Strength": 2}), {"Strength": 2})
        for invalid in (
            {"Strength": 1},
            {"Strength": 3},
            {"Strength": -1, "Arcana": 3},
        ):
            with self.assertRaises(CharacterCreationValidationError):
                parse_bonus_points(invalid)

    def test_every_race_modifier(self) -> None:
        neutral = {attribute: 10 for attribute in ATTRIBUTES}
        for race, modifiers in RACE_MODIFIERS.items():
            actual = apply_modifiers(neutral, {}, race, "Prime")
            for attribute in ATTRIBUTES:
                expected = 10 + modifiers.get(attribute, 0)
                if attribute == "Personality":
                    expected += 1
                self.assertEqual(actual[attribute], expected, (race, attribute))

    def test_every_age_modifier(self) -> None:
        neutral = {attribute: 10 for attribute in ATTRIBUTES}
        for age, modifiers in AGE_MODIFIERS.items():
            actual = apply_modifiers(neutral, {}, "Gnoll", age)
            for attribute in ATTRIBUTES:
                expected = 10 + modifiers.get(attribute, 0)
                if attribute == "Strength":
                    expected += 2
                self.assertEqual(actual[attribute], expected, (age, attribute))

    def test_final_attributes_are_clamped_to_starting_bounds(self) -> None:
        low = {attribute: 8 for attribute in ATTRIBUTES}
        low["Strength"] = 7
        high = {attribute: 16 for attribute in ATTRIBUTES}
        high["Strength"] = 20
        self.assertEqual(apply_modifiers(low, {}, "Human", "Old")["Strength"], 8)
        self.assertEqual(apply_modifiers(high, {}, "Gnoll", "Prime")["Strength"], 16)

    def test_skill_selection_requires_two_distinct_valid_skills(self) -> None:
        self.assertEqual(parse_skills("Melee, Survival"), ("Melee", "Survival"))
        self.assertEqual(parse_skills("1 7"), ("Melee", "Guile"))
        for invalid in ("Melee", "Melee Melee", "Melee Sailing", "Melee Ranged Guile"):
            with self.assertRaises(CharacterCreationValidationError):
                parse_skills(invalid)


class CharacterCreationFlowTests(unittest.TestCase):
    def test_complete_valid_flow_and_result(self) -> None:
        flow = completed_flow()
        self.assertEqual(flow.current_step, CreationStep.COMPLETE)
        result = flow.result
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.name, "Aria")
        self.assertEqual(result.lineage, "Commonfolk")
        self.assertEqual(result.race, "Human")
        self.assertEqual(result.age, "Prime")
        self.assertEqual(result.gender, "Female")
        self.assertEqual(result.base_attributes, VALID_ATTRIBUTES)
        self.assertEqual(result.bonus_points, {"Strength": 1, "Arcana": 1})
        self.assertEqual(result.final_attributes["Strength"], 15)
        self.assertEqual(result.final_attributes["Arcana"], 13)
        self.assertEqual(result.final_attributes["Insight"], 11)
        self.assertEqual(result.final_attributes["Personality"], 11)
        self.assertEqual(result.skill_ranks, {"Melee": 1, "Survival": 1})
        self.assertIn("Aria, Commonfolk Human", result.summary)

    def test_invalid_input_does_not_advance_or_mutate_state(self) -> None:
        flow = CharacterCreationFlow()
        with self.assertRaises(CharacterCreationValidationError):
            flow.submit("invalid")
        self.assertEqual(flow.current_step, CreationStep.LINEAGE)
        self.assertIsNone(flow.state.lineage)

        flow.submit("Fey")
        with self.assertRaises(CharacterCreationValidationError):
            flow.submit("Human")
        self.assertEqual(flow.current_step, CreationStep.RACE)
        self.assertIsNone(flow.state.race)

    def test_reset_restores_a_fresh_flow(self) -> None:
        flow = completed_flow()
        flow.reset()
        self.assertEqual(flow.current_step, CreationStep.LINEAGE)
        self.assertEqual(flow.valid_choices(), LINEAGES)
        self.assertIsNone(flow.result)

    def test_back_navigation_discards_dependent_choices(self) -> None:
        flow = CharacterCreationFlow()
        flow.submit("Fey")
        flow.submit("Elf")
        self.assertEqual(flow.current_step, CreationStep.AGE)

        self.assertEqual(flow.go_back(), CreationStep.RACE)
        self.assertEqual(flow.state.lineage, "Fey")
        self.assertIsNone(flow.state.race)
        self.assertEqual(flow.valid_choices(), RACES_BY_LINEAGE["Fey"])

        self.assertEqual(flow.go_back(), CreationStep.LINEAGE)
        self.assertIsNone(flow.state.lineage)

    def test_valid_choices_reflect_race_and_gender_restrictions(self) -> None:
        flow = CharacterCreationFlow()
        flow.submit("Fey")
        self.assertEqual(flow.valid_choices(), RACES_BY_LINEAGE["Fey"])
        flow.submit("Dryad")
        flow.submit("Young")
        self.assertEqual(flow.valid_choices(), ("Female",))


class CharacterCreationPersistenceTests(unittest.TestCase):
    def test_completed_result_is_persisted_on_existing_character_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "characters.db")
            database.initialize()
            result = completed_flow().result
            assert result is not None
            character = CharacterCreationService(database).persist(42, result)

            self.assertEqual(character.discord_user_id, 42)
            self.assertEqual(character.name, "Aria")
            self.assertEqual(character.max_hp, result.final_attributes["Vitality"])
            self.assertEqual(character.lineage, "Commonfolk")
            self.assertEqual(character.race, "Human")
            self.assertEqual(character.portrait_key, "default/human_female.png")
            self.assertEqual(character.attributes, result.final_attributes)
            self.assertEqual(character.skills, {"Melee": 1, "Survival": 1})
            self.assertEqual(database.get_character(42), character)

            with self.assertRaises(CharacterAlreadyExistsError):
                CharacterCreationService(database).persist(42, result)


if __name__ == "__main__":
    unittest.main()
