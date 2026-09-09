import unittest
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from rpg_bot.character_creation import CharacterCreationFlow, CreationStep
from rpg_bot.commands.character import (
    AttributeLinkSelect,
    AttributeNumberButton,
    AttributeView,
    ArchiveCharacterButton,
    ArchiveConfirmationView,
    BackButton,
    BonusButton,
    BonusView,
    CharacterCommands,
    CharacterManageView,
    CharacterSheetView,
    ChoiceView,
    ConfirmAttributesButton,
    NameView,
    PortraitPreviewView,
    DMPortraitPreviewView,
    SkillView,
    UnequipCharacterButton,
    attribute_prompt,
    attribute_modifier,
    bonus_prompt,
    character_sheet_embed,
    creation_prompt,
    creation_view,
    setup,
)
from rpg_bot.models import Character, Stance
from rpg_bot.inventory import InventoryState
from rpg_bot.portraits import CharacterPortraitStore


def interaction_for(user_id: int) -> SimpleNamespace:
    channel = SimpleNamespace(
        id=55,
        send=AsyncMock(),
        fetch_message=AsyncMock(),
    )
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        client=SimpleNamespace(config=SimpleNamespace(dm_role_name="Dungeon Master")),
        guild_id=44,
        channel=channel,
        response=SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
            send_modal=AsyncMock(),
            defer=AsyncMock(),
        ),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
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

    def test_character_sheet_shows_scores_and_modifiers(self) -> None:
        character = Character(
            7,
            "Olof",
            12,
            15,
            Stance.STEADY,
            race="Troll",
            lineage="Felblood",
            attributes={"Strength": 14, "Dexterity": 9},
            skills={"Melee": 1},
            character_id=3,
        )

        embed = character_sheet_embed(character)

        attributes = next(field.value for field in embed.fields if field.name == "Attributes")
        self.assertIn("Strength** 14 (+2)", attributes)
        self.assertIn("Dexterity** 9 (-1)", attributes)
        self.assertEqual(attribute_modifier(10), 0)
        self.assertEqual(attribute_modifier(11), 0)

    async def test_sheet_opens_privately_with_publish_button(self) -> None:
        character = Character(
            7,
            "Olof",
            12,
            15,
            Stance.STEADY,
            attributes={"Strength": 14},
            character_id=3,
        )
        database = Mock()
        database.get_character.return_value = character
        database.get_inventory.return_value = InventoryState(3, 20, (), {})
        cog = CharacterCommands(database)
        interaction = interaction_for(7)

        await cog.sheet.callback(cog.sheet.binding, interaction)

        call = interaction.response.send_message.await_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertEqual(call.kwargs["embed"].title, "Olof")
        self.assertIsInstance(call.kwargs["view"], CharacterSheetView)
        self.assertEqual(
            [button.label for button in call.kwargs["view"].children],
            ["Inventory", "Publish here"],
        )

    async def test_publishing_sheet_reuses_its_message_in_the_current_channel(self) -> None:
        character = Character(
            7,
            "Olof",
            12,
            15,
            Stance.STEADY,
            attributes={"Strength": 14},
            character_id=3,
        )
        published_message = SimpleNamespace(id=900, edit=AsyncMock())
        database = Mock()
        database.get_character_by_id.return_value = character
        database.get_inventory.return_value = InventoryState(3, 20, (), {})
        database.get_character_sheet_message.side_effect = (None, 900)
        cog = CharacterCommands(database)

        first = interaction_for(7)
        first.channel.send.return_value = published_message
        await cog.publish_character_sheet(first, 7, 3)

        database.set_character_sheet_message.assert_called_once_with(44, 55, 3, 900)
        first.channel.send.assert_awaited_once()

        second = interaction_for(7)
        second.channel.fetch_message.return_value = published_message
        await cog.publish_character_sheet(second, 7, 3)

        second.channel.fetch_message.assert_awaited_once_with(900)
        published_message.edit.assert_awaited_once()
        second.channel.send.assert_not_awaited()
        self.assertIn(
            "Updated",
            second.followup.send.await_args.args[0],
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

    async def test_portrait_upload_updates_active_character_and_shows_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            character = Character(7, "Olof", 12, 12, Stance.STEADY, character_id=3)
            database = Mock()
            database.get_character.return_value = character
            database.get_character_by_id.return_value = character
            database.set_character_portrait.side_effect = lambda user_id, char_id, key: Character(
                user_id,
                "Olof",
                12,
                12,
                Stance.STEADY,
                character_id=char_id,
                portrait_key=key,
            )
            output = BytesIO()
            Image.new("RGB", (320, 180), "blue").save(output, format="PNG")
            attachment = SimpleNamespace(
                size=len(output.getvalue()), read=AsyncMock(return_value=output.getvalue())
            )
            interaction = interaction_for(7)
            cog = CharacterCommands(database, store)

            await cog.portrait.callback(cog.portrait.binding, interaction, attachment)

            interaction.response.defer.assert_awaited_once_with(
                ephemeral=True, thinking=True
            )
            key = database.set_character_portrait.call_args.args[2]
            self.assertTrue((Path(directory) / key).is_file())
            call = interaction.edit_original_response.await_args
            self.assertEqual(call.kwargs["embed"].image.url, "attachment://portrait.webp")
            self.assertEqual(call.kwargs["attachments"][0].filename, "portrait.webp")
            self.assertIsInstance(call.kwargs["view"], PortraitPreviewView)

            remove_interaction = interaction_for(7)
            await call.kwargs["view"].children[0].callback(remove_interaction)

            self.assertEqual(
                database.set_character_portrait.call_args.args,
                (7, 3, None),
            )
            self.assertFalse((Path(directory) / key).exists())
            self.assertIsNone(
                remove_interaction.response.edit_message.await_args.kwargs["view"]
            )

    async def test_portrait_without_upload_shows_existing_image_and_remove_button(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            output = BytesIO()
            Image.new("RGB", (128, 128), "green").save(output, format="PNG")
            key = store.save(3, output.getvalue())
            character = Character(
                7,
                "Olof",
                12,
                12,
                Stance.STEADY,
                character_id=3,
                portrait_key=key,
            )
            database = Mock()
            database.get_character.return_value = character
            database.get_character_by_id.return_value = character
            database.set_character_portrait.return_value = Character(
                7, "Olof", 12, 12, Stance.STEADY, character_id=3
            )
            interaction = interaction_for(7)
            cog = CharacterCommands(database, store)

            await cog.portrait.callback(cog.portrait.binding, interaction)

            call = interaction.response.send_message.await_args
            self.assertEqual(call.kwargs["embed"].image.url, "attachment://portrait.webp")
            self.assertIsInstance(call.kwargs["view"], PortraitPreviewView)
            self.assertTrue(call.kwargs["ephemeral"])

            remove_interaction = interaction_for(7)
            await call.kwargs["view"].children[0].callback(remove_interaction)

            database.set_character_portrait.assert_called_once_with(7, 3, None)
            self.assertFalse((Path(directory) / key).exists())

    async def test_portrait_remove_option_deletes_existing_portrait_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            output = BytesIO()
            Image.new("RGB", (128, 128), "red").save(output, format="PNG")
            key = store.save(3, output.getvalue())
            database = Mock()
            database.get_character.return_value = Character(
                7,
                "Olof",
                12,
                12,
                Stance.STEADY,
                race="Human",
                gender="Male",
                character_id=3,
                portrait_key=key,
            )
            interaction = interaction_for(7)
            cog = CharacterCommands(database, store)

            await cog.portrait.callback(
                cog.portrait.binding, interaction, None, True
            )

            database.set_character_portrait.assert_called_once_with(
                7, 3, "default/human_male.png"
            )
            self.assertFalse((Path(directory) / key).exists())
            self.assertIn(
                "Restored",
                interaction.response.send_message.await_args.args[0],
            )

    @patch("rpg_bot.commands.character.is_dm", return_value=True)
    async def test_dm_without_active_character_can_upload_and_remove_portrait(
        self, _: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CharacterPortraitStore(directory)
            database = Mock()
            database.get_character.return_value = None
            database.get_dm_portrait.return_value = None
            output = BytesIO()
            Image.new("RGB", (180, 120), "purple").save(output, format="PNG")
            attachment = SimpleNamespace(
                size=len(output.getvalue()),
                read=AsyncMock(return_value=output.getvalue()),
            )
            interaction = interaction_for(7)
            cog = CharacterCommands(database, store)

            await cog.portrait.callback(cog.portrait.binding, interaction, attachment)

            key = database.set_dm_portrait.call_args.args[1]
            self.assertRegex(key, r"^dm/7/portrait-[0-9a-f]{32}\.webp$")
            self.assertTrue((Path(directory) / key).is_file())
            view = interaction.edit_original_response.await_args.kwargs["view"]
            self.assertIsInstance(view, DMPortraitPreviewView)

            remove_interaction = interaction_for(7)
            await view.children[0].callback(remove_interaction)

            self.assertEqual(database.set_dm_portrait.call_args.args, (7, None))
            self.assertFalse((Path(directory) / key).exists())

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
        self.assertEqual(len(attributes.children), 10)
        self.assertEqual(
            [
                item.value
                for item in attributes.children
                if isinstance(item, AttributeNumberButton)
            ],
            [14, 13, 12, 11, 10, 9],
        )
        confirm = next(
            item
            for item in attributes.children
            if isinstance(item, ConfirmAttributesButton)
        )
        self.assertTrue(confirm.disabled)

        flow.state.step = CreationStep.BONUS_POINTS
        bonus = creation_view(cog, 7, flow)
        self.assertIsInstance(bonus, BonusView)
        self.assertEqual(len(bonus.children), 14)

        flow.state.step = CreationStep.SKILLS
        skills = creation_view(cog, 7, flow)
        self.assertIsInstance(skills, SkillView)
        self.assertEqual(skills.children[0].min_values, 2)
        self.assertEqual(skills.children[0].max_values, 2)

    async def test_bonus_buttons_update_points_and_enable_confirmation_at_two(self) -> None:
        cog = CharacterCommands(Mock())
        interaction = interaction_for(7)
        flow = CharacterCreationFlow()
        view = BonusView(cog, 7, flow)
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

    async def test_back_button_returns_to_previous_choice_group(self) -> None:
        cog = CharacterCommands(Mock())
        flow = CharacterCreationFlow()
        cog.sessions[7] = flow
        flow.submit("Fey")
        flow.submit("Elf")
        interaction = interaction_for(7)
        view = creation_view(cog, 7, flow)
        back = next(item for item in view.children if isinstance(item, BackButton))

        await back.callback(interaction)

        self.assertEqual(flow.current_step, CreationStep.RACE)
        self.assertIsNone(flow.state.race)
        call = interaction.response.edit_message.await_args
        self.assertIn("Choose a race", call.kwargs["content"])
        self.assertEqual(
            [option.value for option in call.kwargs["view"].children[0].options],
            ["Elf", "Dryad", "Faun"],
        )

    def test_bonus_prompt_shows_current_scores_with_all_modifiers(self) -> None:
        flow = CharacterCreationFlow()
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
        ):
            flow.submit(answer)

        prompt = bonus_prompt(flow, {"Strength": 1})

        self.assertIn("Strength: **15** (bonus +1)", prompt)
        self.assertIn("Insight: **11** (bonus +0)", prompt)
        self.assertIn("Personality: **11** (bonus +0)", prompt)
        self.assertIn("Remaining: **1**", prompt)

    async def test_unequip_button_clears_active_character(self) -> None:
        character = SimpleNamespace(
            character_id=1, name="Olof", is_active=True, is_archived=False
        )
        database = Mock()
        database.list_characters.return_value = [
            SimpleNamespace(
                character_id=1,
                name="Olof",
                is_active=False,
                is_archived=False,
            )
        ]
        cog = CharacterCommands(database)
        view = CharacterManageView(cog, 7, [character], selected_id=1)
        unequip = next(
            item
            for item in view.children
            if isinstance(item, UnequipCharacterButton)
        )
        interaction = interaction_for(7)

        await unequip.callback(interaction)

        database.deactivate_character.assert_called_once_with(7)
        self.assertIn(
            "No character is currently active",
            interaction.response.edit_message.await_args.kwargs["content"],
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
        flow = CharacterCreationFlow()
        self.assertIn("Remaining: **2**", bonus_prompt(flow, {}))


if __name__ == "__main__":
    unittest.main()
