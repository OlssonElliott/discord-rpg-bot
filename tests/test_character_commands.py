import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from rpg_bot.character_creation import CharacterCreationFlow, CreationStep
from rpg_bot.commands.character import (
    AttributeLinkSelect,
    AttributeNumberButton,
    AttributeView,
    ArchiveCharacterButton,
    ArchiveConfirmationView,
    BonusButton,
    BonusView,
    CharacterCommands,
    CharacterManageView,
    ChoiceView,
    NameView,
    SkillView,
    attribute_prompt,
    bonus_prompt,
    creation_prompt,
    creation_view,
    setup,
)


def interaction_for(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
            send_modal=AsyncMock(),
        ),
    )


class CharacterCommandTests(unittest.IsolatedAsyncioTestCase):
    async def invoke_create(self, cog: CharacterCommands, interaction: object) -> None:
        await cog.create.callback(cog.create.binding, interaction)

    async def test_setup_registers_character_cog(self) -> None:
        bot = SimpleNamespace(database=Mock(), add_cog=AsyncMock())
        await setup(bot)
        self.assertIsInstance(bot.add_cog.await_args.args[0], CharacterCommands)

    async def test_create_starts_with_an_ephemeral_lineage_dropdown(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        cog = CharacterCommands(database)
        interaction = interaction_for(7)

        await self.invoke_create(cog, interaction)

        self.assertEqual(cog.sessions[7].current_step, CreationStep.LINEAGE)
        call = interaction.response.send_message.await_args
        self.assertIn("Choose your lineage", call.args[0])
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertIsInstance(call.kwargs["view"], ChoiceView)
        select = call.kwargs["view"].children[0]
        self.assertEqual(
            [option.value for option in select.options],
            ["Commonfolk", "Fey", "Primals", "Felblood", "Wretched"],
        )

    async def test_existing_character_can_start_another_creation(self) -> None:
        database = Mock()
        database.get_character.return_value = object()
        cog = CharacterCommands(database)
        interaction = interaction_for(7)

        await self.invoke_create(cog, interaction)

        self.assertIn(7, cog.sessions)
        self.assertIsInstance(
            interaction.response.send_message.await_args.kwargs["view"], ChoiceView
        )

    async def test_manage_lists_only_selectable_characters(self) -> None:
        first = SimpleNamespace(
            character_id=1, name="Olof", is_active=True, is_archived=False
        )
        second = SimpleNamespace(
            character_id=2, name="Aria", is_active=False, is_archived=False
        )
        database = Mock()
        database.list_characters.return_value = [first, second]
        cog = CharacterCommands(database)
        interaction = interaction_for(7)

        await cog.manage.callback(cog.manage.binding, interaction)

        call = interaction.response.send_message.await_args
        self.assertIn("Olof — active", call.args[0])
        self.assertIsInstance(call.kwargs["view"], CharacterManageView)
        self.assertEqual(
            [option.value for option in call.kwargs["view"].children[0].options],
            ["1", "2"],
        )

    async def test_manage_without_characters_offers_creation(self) -> None:
        database = Mock()
        database.list_characters.return_value = []
        cog = CharacterCommands(database)
        interaction = interaction_for(7)

        await cog.manage.callback(cog.manage.binding, interaction)

        self.assertIn(
            "/character create",
            interaction.response.send_message.await_args.args[0],
        )

    async def test_archiving_requires_confirmation(self) -> None:
        character = SimpleNamespace(
            character_id=1, name="Olof", is_active=True, is_archived=False
        )
        database = Mock()
        cog = CharacterCommands(database)
        view = CharacterManageView(cog, 7, [character], selected_id=1)
        remove_button = next(
            item for item in view.children if isinstance(item, ArchiveCharacterButton)
        )
        interaction = interaction_for(7)

        await remove_button.callback(interaction)

        database.archive_character.assert_not_called()
        call = interaction.response.edit_message.await_args
        self.assertIn("database record will be kept", call.kwargs["content"])
        self.assertIsInstance(call.kwargs["view"], ArchiveConfirmationView)

    async def test_choice_components_advance_and_replace_the_view(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        cog = CharacterCommands(database)
        interaction = interaction_for(7)
        await self.invoke_create(cog, interaction)

        await cog.submit_component(interaction, 7, "Fey")

        self.assertEqual(cog.sessions[7].current_step, CreationStep.RACE)
        call = interaction.response.edit_message.await_args
        self.assertIsInstance(call.kwargs["view"], ChoiceView)
        self.assertEqual(
            [option.value for option in call.kwargs["view"].children[0].options],
            ["Elf", "Dryad", "Faun"],
        )

    async def test_invalid_component_input_keeps_the_current_step(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        cog = CharacterCommands(database)
        interaction = interaction_for(7)
        await self.invoke_create(cog, interaction)

        await cog.submit_component(interaction, 7, "Martian")

        self.assertEqual(cog.sessions[7].current_step, CreationStep.LINEAGE)
        self.assertIn(
            "Choose one of",
            interaction.response.edit_message.await_args.kwargs["content"],
        )

    def test_name_attribute_bonus_and_skill_steps_use_specialized_components(self) -> None:
        database = Mock()
        cog = CharacterCommands(database)
        flow = cog.sessions.setdefault(7, CharacterCreationFlow())

        flow.state.step = CreationStep.NAME
        self.assertIsInstance(creation_view(cog, 7, flow), NameView)

        flow.state.step = CreationStep.ATTRIBUTES
        attributes = creation_view(cog, 7, flow)
        self.assertIsInstance(attributes, AttributeView)
        self.assertEqual(attributes.assignments, {})
        self.assertEqual(len(attributes.children), 9)
        self.assertEqual(
            [
                item.value
                for item in attributes.children
                if isinstance(item, AttributeNumberButton)
            ],
            [14, 13, 12, 11, 10, 9],
        )
        self.assertTrue(attributes.children[-1].disabled)

        flow.state.step = CreationStep.BONUS_POINTS
        bonus = creation_view(cog, 7, flow)
        self.assertIsInstance(bonus, BonusView)
        self.assertEqual(len(bonus.children), 13)

        flow.state.step = CreationStep.SKILLS
        skills = creation_view(cog, 7, flow)
        self.assertIsInstance(skills, SkillView)
        self.assertEqual(skills.children[0].min_values, 2)
        self.assertEqual(skills.children[0].max_values, 2)

    async def test_bonus_buttons_update_points_and_enable_confirmation_at_two(self) -> None:
        cog = CharacterCommands(Mock())
        interaction = interaction_for(7)
        view = BonusView(cog, 7)
        strength_plus = next(
            item
            for item in view.children
            if isinstance(item, BonusButton)
            and item.attribute == "Strength"
            and item.delta == 1
        )

        await strength_plus.callback(interaction)
        updated_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(updated_view.points, {"Strength": 1})
        interaction.response.edit_message.reset_mock()
        strength_plus = next(
            item
            for item in updated_view.children
            if isinstance(item, BonusButton)
            and item.attribute == "Strength"
            and item.delta == 1
        )
        await strength_plus.callback(interaction)
        completed_view = interaction.response.edit_message.await_args.kwargs["view"]

        self.assertEqual(completed_view.points, {"Strength": 2})
        self.assertFalse(completed_view.children[-1].disabled)
        self.assertTrue(
            all(
                item.disabled
                for item in completed_view.children
                if isinstance(item, BonusButton) and item.delta == 1
            )
        )

    async def test_attribute_numbers_can_be_linked_and_relinked(self) -> None:
        cog = CharacterCommands(Mock())
        interaction = interaction_for(7)
        view = AttributeView(cog, 7)
        number_14 = next(
            item
            for item in view.children
            if isinstance(item, AttributeNumberButton) and item.value == 14
        )

        await number_14.callback(interaction)
        selected_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(selected_view.selected_value, 14)
        link_select = next(
            item
            for item in selected_view.children
            if isinstance(item, AttributeLinkSelect)
        )
        link_select._values = ["Strength"]
        interaction.response.edit_message.reset_mock()
        await link_select.callback(interaction)

        linked_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(linked_view.assignments, {"Strength": 14})

        number_13 = next(
            item
            for item in linked_view.children
            if isinstance(item, AttributeNumberButton) and item.value == 13
        )
        await number_13.callback(interaction)
        selected_view = interaction.response.edit_message.await_args.kwargs["view"]
        link_select = next(
            item
            for item in selected_view.children
            if isinstance(item, AttributeLinkSelect)
        )
        link_select._values = ["Dexterity"]
        await link_select.callback(interaction)

        updated_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(
            updated_view.assignments,
            {"Strength": 14, "Dexterity": 13},
        )

        number_14 = next(
            item
            for item in updated_view.children
            if isinstance(item, AttributeNumberButton) and item.value == 14
        )
        await number_14.callback(interaction)
        selected_view = interaction.response.edit_message.await_args.kwargs["view"]
        link_select = next(
            item
            for item in selected_view.children
            if isinstance(item, AttributeLinkSelect)
        )
        link_select._values = ["Dexterity"]
        await link_select.callback(interaction)

        swapped_view = interaction.response.edit_message.await_args.kwargs["view"]
        self.assertEqual(swapped_view.assignments["Strength"], 13)
        self.assertEqual(swapped_view.assignments["Dexterity"], 14)

    async def test_completed_component_flow_is_persisted_and_removes_controls(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        database.create_character.return_value = SimpleNamespace(name="Aria", max_hp=11)
        cog = CharacterCommands(database)
        interaction = interaction_for(7)
        await self.invoke_create(cog, interaction)

        for answer in (
            "Commonfolk",
            "Human",
            "Prime",
            "Female",
            "Aria",
            {
                "Strength": 14,
                "Dexterity": 13,
                "Arcana": 12,
                "Vitality": 11,
                "Insight": 10,
                "Personality": 9,
            },
            {"Strength": 1, "Arcana": 1},
            ("Melee", "Survival"),
        ):
            await cog.submit_component(interaction, 7, answer)

        self.assertNotIn(7, cog.sessions)
        database.create_character.assert_called_once()
        call = database.create_character.call_args
        self.assertEqual(call.args[:3], (7, "Aria", 11))
        self.assertEqual(call.kwargs["skills"], {"Melee": 1, "Survival": 1})
        final_call = interaction.response.edit_message.await_args
        self.assertIn("Created **Aria**", final_call.kwargs["content"])
        self.assertIsNone(final_call.kwargs["view"])

    async def test_cancel_removes_only_calling_users_session(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        cog = CharacterCommands(database)
        first = interaction_for(1)
        second = interaction_for(2)
        await self.invoke_create(cog, first)
        await self.invoke_create(cog, second)

        await cog.cancel.callback(cog.cancel.binding, first)

        self.assertNotIn(1, cog.sessions)
        self.assertIn(2, cog.sessions)

    def test_prompts_are_short_ui_copy(self) -> None:
        prompt = creation_prompt(CharacterCreationFlow())
        self.assertNotIn("DM:", prompt)
        self.assertLess(len(attribute_prompt({})), 350)
        self.assertIn("**14** → Not assigned", attribute_prompt({}))
        self.assertIn("Select a number button", attribute_prompt({}))
        self.assertIn("Remaining: **2**", bonus_prompt({}))


if __name__ == "__main__":
    unittest.main()
