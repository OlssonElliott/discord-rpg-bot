import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from rpg_bot.commands.player import (
    PlayerCommands,
    dice_glow_colors,
    dice_color_autocomplete,
    setup,
)
from rpg_bot.dice import DiceRoll
from rpg_bot.dice_assets import DiceAsset
from rpg_bot.dice_visuals import InvalidDiceColorError, RenderedDiceAnimation
from rpg_bot.models import Character, Stance
from rpg_bot.portraits import CharacterPortraitStore


class FakeMember:
    def __init__(self, user_id: int, roles: list[str]) -> None:
        self.id = user_id
        self.roles = [SimpleNamespace(name=name) for name in roles]


def interaction_for(user: FakeMember) -> SimpleNamespace:
    return SimpleNamespace(
        user=user,
        client=SimpleNamespace(config=SimpleNamespace(dm_role_name="Dungeon Master")),
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


class PlayerCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_critical_glow_is_assigned_per_die(self) -> None:
        self.assertEqual(
            dice_glow_colors(20, (15, 6, 1, 20), "normal"),
            (None, None, "#E74C3C", "#2ECC71"),
        )
        self.assertEqual(
            dice_glow_colors(20, (1, 17), "advantage"),
            ("#E74C3C", "#2ECC71"),
        )
        self.assertEqual(dice_glow_colors(6, (1,), "normal"), (None,))

    async def invoke_roll(self, database: Mock, interaction: SimpleNamespace) -> None:
        command = PlayerCommands(database).roll_command
        await command.callback(command.binding, interaction, "2d6+3")

    async def invoke_dice_color(
        self, database: Mock, interaction: SimpleNamespace, color: str | None
    ) -> None:
        command = PlayerCommands(database).dice_color
        await command.callback(command.binding, interaction, color)

    async def invoke_dice_edge_color(
        self, database: Mock, interaction: SimpleNamespace, color: str | None
    ) -> None:
        command = PlayerCommands(database).dice_edge_color
        await command.callback(command.binding, interaction, color)

    async def invoke_dice_number_color(
        self, database: Mock, interaction: SimpleNamespace, color: str | None
    ) -> None:
        command = PlayerCommands(database).dice_number_color
        await command.callback(command.binding, interaction, color)

    async def test_setup_uses_the_configured_global_theme(self) -> None:
        bot = SimpleNamespace(
            database=Mock(),
            config=SimpleNamespace(dice_theme="cartoon"),
            add_cog=AsyncMock(),
        )

        await setup(bot)

        cog = bot.add_cog.await_args.args[0]
        self.assertEqual(cog.animation_renderer.theme, "cartoon")

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    async def test_player_without_character_cannot_roll(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        interaction = interaction_for(FakeMember(1, ["Player"]))

        await self.invoke_roll(database, interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "You do not have an active character. Use `/character manage` "
            "to equip one or `/character create` to make one.",
            ephemeral=True,
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("2d6+3", 2, 6, 3, (2, 5)))
    async def test_dm_without_character_gets_generic_roll_embed(self, _: Mock) -> None:
        database = Mock()
        database.get_character.return_value = None
        interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))

        await self.invoke_roll(database, interaction)

        call = interaction.response.send_message.await_args
        embed = call.kwargs["embed"]
        self.assertEqual(embed.title, "DM Roll")
        self.assertEqual(
            embed.thumbnail.url, "attachment://character_portrait.png"
        )
        self.assertEqual(
            call.kwargs["file"].filename,
            "character_portrait.png",
        )
        self.assertEqual(
            [(field.name, field.value) for field in embed.fields],
            [
                ("Expression", "`2d6+3`"),
                ("2d6", "2, 5"),
                ("Modifier", "+3"),
                ("Total", "**10**"),
            ],
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("2d6+3", 2, 6, 3, (2, 5)))
    async def test_dm_with_character_keeps_character_roll_embed(self, _: Mock) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=2,
            name="Merlin",
            hp=8,
            max_hp=12,
            stance=Stance.PRONE,
        )
        interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))

        await self.invoke_roll(database, interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        self.assertIsNone(embed.title)
        self.assertEqual(embed.author.name, "Merlin")
        self.assertEqual(
            [(field.name, field.value) for field in embed.fields[-2:]],
            [("HP", "8/12"), ("Stance", "Prone")],
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("1d100", 1, 100, 0, (42,)))
    async def test_portrait_is_attached_to_instant_character_roll(self, _: Mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            portrait_path = Path(directory) / "9" / "portrait.webp"
            portrait_path.parent.mkdir()
            portrait_path.write_bytes(b"portrait")
            store = CharacterPortraitStore(directory)
            database = Mock()
            database.get_character.return_value = Character(
                discord_user_id=3,
                name="Olof",
                hp=12,
                max_hp=12,
                stance=Stance.STEADY,
                character_id=9,
                portrait_key="9/portrait.webp",
            )
            interaction = interaction_for(FakeMember(3, ["Player"]))
            command = PlayerCommands(database, portrait_store=store).roll_command

            await command.callback(command.binding, interaction, "1d100")

        call = interaction.response.send_message.await_args
        self.assertEqual(call.kwargs["file"].filename, "character_portrait.webp")
        self.assertEqual(
            call.kwargs["embed"].thumbnail.url,
            "attachment://character_portrait.webp",
        )
        self.assertEqual(call.kwargs["embed"].author.name, "Olof")

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("1d100", 1, 100, 0, (42,)))
    async def test_default_race_portrait_is_attached_to_roll(self, _: Mock) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=3,
            name="Aria",
            hp=11,
            max_hp=11,
            stance=Stance.STEADY,
            race="Human",
            gender="Female",
            character_id=10,
            portrait_key="default/human_female.png",
        )
        interaction = interaction_for(FakeMember(3, ["Player"]))
        command = PlayerCommands(database).roll_command

        await command.callback(command.binding, interaction, "1d100")

        call = interaction.response.send_message.await_args
        self.assertEqual(call.kwargs["file"].filename, "character_portrait.png")
        self.assertEqual(
            call.kwargs["embed"].thumbnail.url,
            "attachment://character_portrait.png",
        )

    async def test_dice_color_can_be_viewed_or_updated_without_a_character(self) -> None:
        database = Mock()
        database.get_dice_color.return_value = "#C89B3C"
        database.set_dice_color.return_value = "#7A2EFF"

        view_interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))
        await self.invoke_dice_color(database, view_interaction, None)
        view_embed = view_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(view_embed.title, "Your Dice Color")
        self.assertEqual(view_embed.description, "Your dice color is `#C89B3C`.")

        update_interaction = interaction_for(FakeMember(3, ["Player"]))
        await self.invoke_dice_color(database, update_interaction, "7a2eff")
        database.set_dice_color.assert_called_once_with(3, "7a2eff")
        update_embed = update_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(update_embed.title, "Dice Color Updated")
        self.assertEqual(update_embed.colour.value, 0x7A2EFF)

    async def test_bad_dice_color_gets_a_friendly_ephemeral_error(self) -> None:
        database = Mock()
        database.set_dice_color.side_effect = InvalidDiceColorError(
            "Use a six-digit hexadecimal color such as `#7A2EFF`."
        )
        interaction = interaction_for(FakeMember(3, ["Player"]))

        await self.invoke_dice_color(database, interaction, "purple")

        interaction.response.send_message.assert_awaited_once_with(
            "Use a six-digit hexadecimal color such as `#7A2EFF`.", ephemeral=True
        )

    async def test_dice_edge_color_can_be_viewed_and_updated_per_player(self) -> None:
        database = Mock()
        database.get_dice_edge_color.return_value = "#303030"
        database.set_dice_edge_color.return_value = "#FFD700"

        view_interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))
        await self.invoke_dice_edge_color(database, view_interaction, None)
        view_embed = view_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(view_embed.title, "Your Dice Edge Color")
        self.assertEqual(view_embed.description, "Your dice edge color is `#303030`.")

        update_interaction = interaction_for(FakeMember(3, ["Player"]))
        await self.invoke_dice_edge_color(database, update_interaction, "ffd700")
        database.set_dice_edge_color.assert_called_once_with(3, "ffd700")
        update_embed = update_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(update_embed.title, "Dice Edge Color Updated")
        self.assertEqual(update_embed.colour.value, 0xFFD700)

    async def test_dice_number_color_can_be_viewed_and_updated_per_player(self) -> None:
        database = Mock()
        database.get_dice_number_color.return_value = "#101010"
        database.set_dice_number_color.return_value = "#F5F5F5"

        view_interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))
        await self.invoke_dice_number_color(database, view_interaction, None)
        view_embed = view_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(view_embed.title, "Your Dice Number Color")
        self.assertEqual(view_embed.description, "Your dice number color is `#101010`.")

        update_interaction = interaction_for(FakeMember(3, ["Player"]))
        await self.invoke_dice_number_color(database, update_interaction, "f5f5f5")
        database.set_dice_number_color.assert_called_once_with(3, "f5f5f5")
        update_embed = update_interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(update_embed.title, "Dice Number Color Updated")
        self.assertEqual(update_embed.colour.value, 0xF5F5F5)

    async def test_color_autocomplete_offers_named_hex_suggestions(self) -> None:
        choices = await dice_color_autocomplete(Mock(), "purple")

        self.assertEqual([choice.value for choice in choices], ["#7A2EFF"])
        self.assertIn("Royal Purple", choices[0].name)

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.asyncio.sleep", new_callable=AsyncMock)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("1d20+4", 1, 20, 4, (17,)))
    async def test_single_d20_animation_is_replaced_by_result_embed(
        self, _: Mock, sleep: AsyncMock
    ) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=3,
            name="Olof",
            hp=12,
            max_hp=12,
            stance=Stance.STEADY,
        )
        database.get_dice_color.return_value = "#7A2EFF"
        database.get_dice_edge_color.return_value = "#FFD700"
        database.get_dice_number_color.return_value = "#F5F5F5"
        interaction = interaction_for(FakeMember(3, ["Player"]))

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            master_path = assets / "d20_17.gif"
            master_path.write_bytes(b"master")
            master_asset = DiceAsset(master_path, "cartoon")
            generated_path = assets / "d20_17_7A2EFF.gif"
            generated_path.write_bytes(b"generated")
            result_image_path = assets / "d20_17_7A2EFF_result.png"
            result_image_path.write_bytes(b"result")
            renderer = Mock()
            renderer.resolve_master.return_value = master_asset
            renderer.render.return_value = RenderedDiceAnimation(
                generated_path, 1.25, result_image_path
            )
            command = PlayerCommands(database, renderer).roll_command

            await command.callback(command.binding, interaction, "1d20+4")

        interaction.response.defer.assert_awaited_once_with(thinking=True)
        renderer.resolve_master.assert_called_once_with(17, 20)
        renderer.render.assert_called_once_with(
            17, "#7A2EFF", master_asset, "#FFD700", "#F5F5F5", 20
        )
        sleep.assert_awaited_once_with(1.2)
        self.assertEqual(interaction.edit_original_response.await_count, 2)
        final_call = interaction.edit_original_response.await_args_list[-1]
        self.assertEqual(final_call.kwargs["embed"].fields[3].value, "**21**")
        self.assertEqual(
            final_call.kwargs["embed"].image.url,
            "attachment://d20_17_result.png",
        )
        self.assertEqual(len(final_call.kwargs["attachments"]), 1)
        self.assertEqual(
            final_call.kwargs["attachments"][0].filename,
            "d20_17_result.png",
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.asyncio.sleep", new_callable=AsyncMock)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("1d6+2", 1, 6, 2, (4,)))
    async def test_single_supported_non_d20_uses_visual_animation(
        self, _: Mock, sleep: AsyncMock
    ) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=3,
            name="Olof",
            hp=12,
            max_hp=12,
            stance=Stance.STEADY,
        )
        database.get_dice_color.return_value = "#7A2EFF"
        database.get_dice_edge_color.return_value = "#FFD700"
        database.get_dice_number_color.return_value = "#101010"
        interaction = interaction_for(FakeMember(3, ["Player"]))

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            master_path = assets / "d6_4.gif"
            master_path.write_bytes(b"master")
            master_asset = DiceAsset(master_path, "cartoon")
            generated_path = assets / "d6_4_7A2EFF.gif"
            generated_path.write_bytes(b"generated")
            result_image_path = assets / "d6_4_result.png"
            result_image_path.write_bytes(b"result")
            renderer = Mock()
            renderer.resolve_master.return_value = master_asset
            renderer.render.return_value = RenderedDiceAnimation(
                generated_path, 1.25, result_image_path
            )
            command = PlayerCommands(database, renderer).roll_command

            await command.callback(command.binding, interaction, "1d6+2")

        renderer.resolve_master.assert_called_once_with(4, 6)
        renderer.render.assert_called_once_with(
            4, "#7A2EFF", master_asset, "#FFD700", "#101010", 6
        )
        sleep.assert_awaited_once_with(1.2)
        final_call = interaction.edit_original_response.await_args_list[-1]
        self.assertEqual(
            final_call.kwargs["embed"].image.url,
            "attachment://d6_4_result.png",
        )
        self.assertEqual(
            final_call.kwargs["attachments"][0].filename,
            "d6_4_result.png",
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.asyncio.sleep", new_callable=AsyncMock)
    @patch("rpg_bot.commands.player.roll", return_value=DiceRoll("3d6+2", 3, 6, 2, (2, 5, 1)))
    async def test_multiple_dice_use_a_group_animation_and_result_strip(
        self, _: Mock, sleep: AsyncMock
    ) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=3,
            name="Olof",
            hp=12,
            max_hp=12,
            stance=Stance.STEADY,
        )
        database.get_dice_color.return_value = "#7A2EFF"
        database.get_dice_edge_color.return_value = "#FFD700"
        database.get_dice_number_color.return_value = "#101010"
        interaction = interaction_for(FakeMember(3, ["Player"]))

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            masters = tuple(
                DiceAsset(assets / f"d6_{value}.gif", "cartoon")
                for value in (2, 5, 1)
            )
            for master in masters:
                master.path.write_bytes(b"master")
            generated_path = assets / "d6_2-5-1.gif"
            generated_path.write_bytes(b"generated")
            result_image_path = assets / "d6_2-5-1_results.png"
            result_image_path.write_bytes(b"result")
            renderer = Mock()
            renderer.resolve_master.side_effect = masters
            renderer.render_many.return_value = RenderedDiceAnimation(
                generated_path, 1.25, result_image_path
            )
            sound_manager = Mock()
            sound_manager.prepare = AsyncMock(return_value="voice-client")
            command = PlayerCommands(database, renderer, sound_manager).roll_command

            await command.callback(command.binding, interaction, "3d6+2")

        self.assertEqual(
            renderer.resolve_master.call_args_list,
            [
                unittest.mock.call(2, 6),
                unittest.mock.call(5, 6),
                unittest.mock.call(1, 6),
            ],
        )
        renderer.render_many.assert_called_once_with(
            (2, 5, 1),
            "#7A2EFF",
            masters,
            "#FFD700",
            "#101010",
            6,
            None,
            glow_colors=(None, None, None),
        )
        sound_manager.prepare.assert_awaited_once_with(interaction)
        sound_manager.play_spin.assert_called_once_with("voice-client", 1.25)
        sound_manager.play_result.assert_called_once_with(
            "voice-client", 6, (2, 5, 1), None
        )
        sleep.assert_awaited_once_with(1.2)
        self.assertEqual(interaction.edit_original_response.await_count, 2)
        animation_call = interaction.edit_original_response.await_args_list[0]
        self.assertEqual(
            animation_call.kwargs["attachments"][0].filename,
            "d6_2-5-1.gif",
        )
        final_call = interaction.edit_original_response.await_args_list[-1]
        self.assertEqual(
            final_call.kwargs["embed"].image.url,
            "attachment://d6_2-5-1_results.png",
        )
        self.assertEqual(
            final_call.kwargs["attachments"][0].filename,
            "d6_2-5-1_results.png",
        )

    @patch("rpg_bot.checks.discord.Member", FakeMember)
    @patch("rpg_bot.commands.player.asyncio.sleep", new_callable=AsyncMock)
    @patch(
        "rpg_bot.commands.player.roll",
        return_value=DiceRoll("1d20+4", 2, 20, 4, (6, 17), kept_result=17),
    )
    async def test_advantage_glows_green_and_highlights_the_kept_die(
        self, mocked_roll: Mock, sleep: AsyncMock
    ) -> None:
        database = Mock()
        database.get_character.return_value = Character(
            discord_user_id=3,
            name="Olof",
            hp=12,
            max_hp=12,
            stance=Stance.STEADY,
        )
        database.get_dice_color.return_value = "#7A2EFF"
        database.get_dice_edge_color.return_value = "#FFD700"
        database.get_dice_number_color.return_value = "#101010"
        interaction = interaction_for(FakeMember(3, ["Player"]))

        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            masters = (
                DiceAsset(assets / "d20_6.gif", "cartoon"),
                DiceAsset(assets / "d20_17.gif", "cartoon"),
            )
            for master in masters:
                master.path.write_bytes(b"master")
            generated_path = assets / "advantage.gif"
            generated_path.write_bytes(b"generated")
            result_image_path = assets / "advantage_results.png"
            result_image_path.write_bytes(b"result")
            renderer = Mock()
            renderer.resolve_master.side_effect = masters
            renderer.render_many.return_value = RenderedDiceAnimation(
                generated_path, 1.25, result_image_path
            )
            sound_manager = Mock()
            sound_manager.prepare = AsyncMock(return_value="voice-client")
            command = PlayerCommands(database, renderer, sound_manager).roll_command

            await command.callback(
                command.binding,
                interaction,
                "1d20+4",
                "advantage",
            )

        mocked_roll.assert_called_once_with("1d20+4", mode="advantage")
        sound_manager.prepare.assert_awaited_once_with(interaction)
        sound_manager.play_spin.assert_called_once_with("voice-client", 1.25)
        sound_manager.play_result.assert_called_once_with(
            "voice-client", 20, (6, 17), 17
        )
        renderer.render_many.assert_called_once_with(
            (6, 17),
            "#7A2EFF",
            masters,
            "#FFD700",
            "#101010",
            20,
            1,
            glow_colors=("#2ECC71", "#2ECC71"),
        )
        sleep.assert_awaited_once_with(1.2)
        animation_call = interaction.edit_original_response.await_args_list[0]
        self.assertEqual(
            animation_call.kwargs["content"],
            "Rolling 1d20+4 with advantage…",
        )
        final_embed = interaction.edit_original_response.await_args_list[-1].kwargs[
            "embed"
        ]
        self.assertEqual(final_embed.colour.value, 0x2ECC71)
        self.assertEqual(final_embed.fields[1].name, "🟢 Advantage")
        self.assertEqual(final_embed.fields[2].value, "6, **17** ✓")
        self.assertEqual(
            final_embed.image.url,
            "attachment://d20_6-17_results.png",
        )


if __name__ == "__main__":
    unittest.main()
