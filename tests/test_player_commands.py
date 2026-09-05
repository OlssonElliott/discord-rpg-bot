import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from commands.player import PlayerCommands
from dice import DiceRoll
from models import Character, Stance


class FakeMember:
    def __init__(self, user_id: int, roles: list[str]) -> None:
        self.id = user_id
        self.roles = [SimpleNamespace(name=name) for name in roles]


def interaction_for(user: FakeMember) -> SimpleNamespace:
    return SimpleNamespace(
        user=user,
        client=SimpleNamespace(config=SimpleNamespace(dm_role_name="Dungeon Master")),
        response=SimpleNamespace(send_message=AsyncMock()),
    )


class PlayerCommandTests(unittest.IsolatedAsyncioTestCase):
    async def invoke_roll(self, database: Mock, interaction: SimpleNamespace) -> None:
        command = PlayerCommands(database).roll_command
        await command.callback(command.binding, interaction, "2d6+3")

    @patch("checks.discord.Member", FakeMember)
    async def test_player_without_character_cannot_roll(self) -> None:
        database = Mock()
        database.get_character.return_value = None
        interaction = interaction_for(FakeMember(1, ["Player"]))

        await self.invoke_roll(database, interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "You do not have a character yet. Ask your DM to use `/createcharacter`.",
            ephemeral=True,
        )

    @patch("checks.discord.Member", FakeMember)
    @patch("commands.player.roll", return_value=DiceRoll("2d6+3", 2, 6, 3, (2, 5)))
    async def test_dm_without_character_gets_generic_roll_embed(self, _: Mock) -> None:
        database = Mock()
        database.get_character.return_value = None
        interaction = interaction_for(FakeMember(2, ["Dungeon Master"]))

        await self.invoke_roll(database, interaction)

        embed = interaction.response.send_message.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "DM Roll")
        self.assertEqual(
            [(field.name, field.value) for field in embed.fields],
            [
                ("Expression", "`2d6+3`"),
                ("2d6", "2, 5"),
                ("Modifier", "+3"),
                ("Total", "**10**"),
            ],
        )

    @patch("checks.discord.Member", FakeMember)
    @patch("commands.player.roll", return_value=DiceRoll("2d6+3", 2, 6, 3, (2, 5)))
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
        self.assertEqual(embed.title, "Merlin — Dice Roll")
        self.assertEqual(
            [(field.name, field.value) for field in embed.fields[-2:]],
            [("HP", "8/12"), ("Stance", "Prone")],
        )


if __name__ == "__main__":
    unittest.main()
