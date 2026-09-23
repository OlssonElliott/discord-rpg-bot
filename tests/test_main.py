import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from rpg_bot.app.bot import RPGBot


class BotSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_loads_player_transfer_commands(self) -> None:
        bot = SimpleNamespace(
            config=SimpleNamespace(discord_guild_id=None),
            load_extension=AsyncMock(),
            tree=SimpleNamespace(sync=AsyncMock(return_value=())),
        )

        await RPGBot.setup_hook(bot)

        bot.load_extension.assert_any_await("rpg_bot.commands.give")
        bot.load_extension.assert_any_await("rpg_bot.commands.combat")
