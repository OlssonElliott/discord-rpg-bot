import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from rpg_bot.commands.combat import ensure_combat_channel
from rpg_bot.discord_support.combat_messages import CombatMessageStore


class CombatChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_combat_channel_is_reused(self) -> None:
        channel = SimpleNamespace(name="combat")
        guild = SimpleNamespace(
            id=44,
            text_channels=[channel],
            create_text_channel=AsyncMock(),
        )

        resolved = await ensure_combat_channel(guild)

        self.assertIs(resolved, channel)
        guild.create_text_channel.assert_not_awaited()

    async def test_combat_channel_is_created_once_when_missing(self) -> None:
        channel = SimpleNamespace(name="combat")
        guild = SimpleNamespace(
            id=44,
            text_channels=[],
            me=SimpleNamespace(
                guild_permissions=SimpleNamespace(manage_channels=True)
            ),
            create_text_channel=AsyncMock(return_value=channel),
        )

        resolved = await ensure_combat_channel(guild)

        self.assertIs(resolved, channel)
        guild.create_text_channel.assert_awaited_once_with(
            "combat",
            topic="Shared landmark-based combat scene and turn state.",
            reason="Public Rollkeeper combat channel",
        )


class CombatMessageStoreTests(unittest.TestCase):
    def test_saved_dashboard_message_survives_reinitialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "combat.db"
            first = CombatMessageStore(db_path)
            self.assertIsNone(first.get(44))
            first.save(44, 7, 111, 222)
            second = CombatMessageStore(db_path)
            entry = second.get(44)
            self.assertIsNotNone(entry)
            self.assertEqual((entry.scene_id, entry.channel_id, entry.message_id), (7, 111, 222))
            second.save(44, 8, 111, 333)
            self.assertEqual(first.get(44).message_id, 333)
            first.clear(44)
            self.assertIsNone(second.get(44))



if __name__ == "__main__":
    unittest.main()
