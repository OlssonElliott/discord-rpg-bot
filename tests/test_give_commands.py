import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rpg_bot.commands.give import GiveCommands, GiveOffer, GiveSetupView, RoomRecipient
from rpg_bot.database import Database
from rpg_bot.inventory_service import InventoryError
from rpg_bot.world_service import WorldService


class GiveCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_directory.name) / "give.db")
        self.database.initialize()
        self.sender = self.database.create_character(
            7,
            "Olof",
            15,
            attributes={"Strength": 14, "Vitality": 15},
        )
        self.recipient = self.database.create_character(
            8,
            "Mira",
            15,
            attributes={"Strength": 14, "Vitality": 15},
        )
        self.cog = GiveCommands(self.database)
        self.world = WorldService(self.database, self.cog.catalog)
        self.world.create_area("crypt", "Crypt")
        self.world.create_room("hall", "crypt", "Hall")
        self.world.create_room("cellar", "crypt", "Cellar")
        self.world.place_character(self.sender.character_id, "hall")
        self.world.place_character(self.recipient.character_id, "hall")
        self.outsider = self.database.create_character(
            9,
            "Sven",
            12,
            attributes={"Strength": 12},
        )
        self.world.place_character(self.outsider.character_id, "cellar")
        self.rollkeeper = self.database.create_character(
            999,
            "Rollkeeper",
            99,
            attributes={"Strength": 99},
        )
        self.world.place_character(self.rollkeeper.character_id, "hall")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_recipient_choices_only_include_other_characters_in_same_room(self) -> None:
        recipients = self.cog.room_recipients(7)

        self.assertEqual(
            [(recipient.user_id, recipient.name) for recipient in recipients],
            [(8, "Mira")],
        )

    def test_recipient_discovery_reads_room_from_persisted_character_state(self) -> None:
        stale_sender = SimpleNamespace(
            character_id=self.sender.character_id,
            current_room_id=None,
        )
        original_character = self.cog._character
        self.cog._character = lambda user_id: (
            stale_sender if user_id == 7 else original_character(user_id)
        )
        try:
            recipients = self.cog.room_recipients(7)
        finally:
            self.cog._character = original_character

        self.assertEqual(
            [
                (recipient.character_id, recipient.user_id, recipient.name)
                for recipient in recipients
            ],
            [(self.recipient.character_id, 8, "Mira")],
        )

    def test_recipient_discovery_does_not_require_discord_channel_membership(self) -> None:
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            channel=SimpleNamespace(members=[SimpleNamespace(id=7)]),
        )

        recipients = self.cog.room_recipients(interaction.user.id)

        self.assertEqual([recipient.name for recipient in recipients], ["Mira"])

    def test_recipient_discovery_is_not_based_on_discord_channel_state(self) -> None:
        recipients = self.cog.room_recipients(7)

        self.assertEqual(
            [(recipient.character_id, recipient.user_id, recipient.name)
             for recipient in recipients],
            [(self.recipient.character_id, 8, "Mira")],
        )

        self.world.place_character(self.recipient.character_id, "cellar")

        self.assertEqual(
            [
                recipient.character_id
                for recipient in self.cog.room_recipients(7)
            ],
            [],
        )

    def test_same_room_character_does_not_need_to_be_active_to_be_listed(self) -> None:
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE id = ?",
                (self.recipient.character_id,),
            )

        recipients = self.cog.room_recipients(7)

        self.assertEqual(
            [(recipient.character_id, recipient.user_id, recipient.name)
             for recipient in recipients],
            [(self.recipient.character_id, 8, "Mira")],
        )

    def test_transfer_targets_same_room_character_even_when_not_active(self) -> None:
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE id = ?",
                (self.recipient.character_id,),
            )
        self.cog.inventory_service.grant_currency(self.sender, copper=5)

        result = self.cog.accept_offer(
            GiveOffer(
                sender_user_id=7,
                recipient_user_id=8,
                copper=2,
            )
        )

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        self.assertEqual(sender_inventory.copper, 3)
        self.assertEqual(recipient_inventory.copper, 2)
        self.assertIn("Mira", result)

    def test_rollkeeper_cannot_be_a_transfer_recipient(self) -> None:
        with self.assertRaisesRegex(ValueError, "Rollkeeper"):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=999,
                    copper=1,
                )
            )

    def test_recipient_autocomplete_excludes_rollkeeper_bot(self) -> None:
        self.cog.room_recipients = lambda _user_id: (
            RoomRecipient(user_id=8, character_id=self.recipient.character_id, name="Mira"),
            RoomRecipient(user_id=999, character_id=999, name="Rollkeeper"),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            client=SimpleNamespace(user=SimpleNamespace(id=999)),
        )

        choices = asyncio.run(self.cog.player_autocomplete(interaction, ""))

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Mira", str(self.recipient.character_id))],
        )

    def test_recipient_autocomplete_is_character_based_not_discord_user_based(self) -> None:
        self.cog.room_recipients = lambda _user_id: (
            RoomRecipient(
                user_id=8,
                character_id=self.recipient.character_id,
                name="Mira",
            ),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            client=SimpleNamespace(user=SimpleNamespace(id=8)),
        )

        choices = asyncio.run(self.cog.player_autocomplete(interaction, ""))

        self.assertEqual(
            [(choice.name, choice.value) for choice in choices],
            [("Mira", str(self.recipient.character_id))],
        )

    def test_item_choices_only_include_senders_inventory(self) -> None:
        potion_id = self.cog.inventory_service.grant(
            self.sender,
            "health_potion",
            2,
        )
        self.cog.inventory_service.grant(self.recipient, "iron_dagger")
        interaction = SimpleNamespace(user=SimpleNamespace(id=7))

        choices = asyncio.run(self.cog.item_autocomplete(interaction, ""))

        self.assertEqual([choice.value for choice in choices], [potion_id])
        self.assertEqual(choices[0].name, "Health Potion ×2")

    def test_give_menu_only_contains_valid_recipient_and_owned_items(self) -> None:
        potion_id = self.cog.inventory_service.grant(
            self.sender,
            "health_potion",
            2,
        )
        self.cog.inventory_service.grant(self.recipient, "iron_dagger")

        async def build_view():
            return GiveSetupView(
                self.cog,
                7,
                self.cog.room_recipients(7),
                items=self.cog.give_item_choices(7),
            )

        view = asyncio.run(build_view())
        recipient_select = next(
            child for child in view.children
            if getattr(child, "custom_id", None) == "give:recipient"
        )
        item_select = next(
            child for child in view.children
            if getattr(child, "custom_id", None) == "give:item"
        )

        self.assertEqual(
            [(option.label, option.value) for option in recipient_select.options],
            [("Mira", str(self.recipient.character_id))],
        )
        self.assertEqual(
            [(option.label, option.value) for option in item_select.options],
            [("Health Potion ×2", potion_id)],
        )
        self.assertEqual(
            {
                child.custom_id
                for child in view.children
                if getattr(child, "custom_id", None)
            },
            {
                "give:recipient",
                "give:item",
                "give:quantity",
                "give:coins",
                "give:confirm",
            },
        )
        self.assertTrue(view.quantity_button.disabled)
        view.stop()

    def test_give_command_uses_the_private_menu_not_slash_options(self) -> None:
        self.assertEqual(
            list(inspect.signature(GiveCommands.give.callback).parameters),
            ["self", "interaction"],
        )

    def test_multiple_characters_for_one_user_target_exact_selected_character(self) -> None:
        other_recipient = self.database.create_character(
            8,
            "Other Mira",
            12,
            attributes={"Strength": 12},
        )
        self.world.place_character(other_recipient.character_id, "hall")

        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE id = ?",
                (other_recipient.character_id,),
            )
            connection.execute(
                "UPDATE characters SET is_active = 1 WHERE id = ?",
                (self.recipient.character_id,),
            )

        self.cog.inventory_service.grant_currency(self.sender, copper=5)

        recipients = self.cog.room_recipients(7)
        self.assertEqual(
            {
                (recipient.character_id, recipient.user_id, recipient.name)
                for recipient in recipients
            },
            {
                (self.recipient.character_id, 8, "Mira"),
                (other_recipient.character_id, 8, "Other Mira"),
            },
        )

        offer = self.cog.create_offer(
            7,
            other_recipient.character_id,
            copper=2,
        )

        self.assertEqual(offer.recipient_user_id, 8)
        self.assertEqual(
            offer.recipient_character_id,
            other_recipient.character_id,
        )

        result = self.cog.accept_offer(offer)

        original_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        other_inventory = self.database.get_character_inventory(
            other_recipient.character_id
        )
        self.assertEqual(original_inventory.copper, 0)
        self.assertEqual(other_inventory.copper, 2)
        self.assertIn("Other Mira", result)

    def test_same_discord_users_other_character_is_not_a_recipient(self) -> None:
        other_sender_character = self.database.create_character(
            7,
            "Olof Two",
            12,
            attributes={"Strength": 12},
        )
        self.world.place_character(other_sender_character.character_id, "hall")

        with self.database._connect() as connection:
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE id = ?",
                (other_sender_character.character_id,),
            )
            connection.execute(
                "UPDATE characters SET is_active = 1 WHERE id = ?",
                (self.sender.character_id,),
            )
        self.assertNotIn(
            other_sender_character.character_id,
            [recipient.character_id for recipient in self.cog.room_recipients(7)],
        )

        with self.assertRaisesRegex(ValueError, "another character"):
            self.cog.create_offer(
                7,
                other_sender_character.character_id,
                copper=2,
            )

        self.cog.inventory_service.grant_currency(self.sender, copper=5)
        with self.assertRaisesRegex(ValueError, "yourself"):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=7,
                    sender_character_id=self.sender.character_id,
                    recipient_character_id=other_sender_character.character_id,
                    copper=2,
                )
            )

    def test_cannot_give_item_owned_by_another_character(self) -> None:
        recipient_item_id = self.cog.inventory_service.grant(
            self.recipient,
            "iron_dagger",
        )

        with self.assertRaisesRegex(ValueError, "own inventory"):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=8,
                    item_instance_id=recipient_item_id,
                    quantity=1,
                )
            )

    def test_transfer_is_rejected_after_recipient_leaves_room(self) -> None:
        self.cog.inventory_service.grant_currency(self.sender, copper=5)
        self.world.place_character(self.recipient.character_id, "cellar")

        with self.assertRaisesRegex(ValueError, "room"):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=8,
                    copper=1,
                )
            )

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        self.assertEqual(sender_inventory.copper, 5)
        self.assertEqual(recipient_inventory.copper, 0)

    def test_created_offer_is_rejected_after_recipient_leaves_room(self) -> None:
        self.cog.inventory_service.grant_currency(self.sender, copper=5)
        offer = self.cog.create_offer(
            7,
            self.recipient.character_id,
            copper=1,
        )

        self.world.place_character(self.recipient.character_id, "cellar")

        with self.assertRaisesRegex(ValueError, "room"):
            self.cog.accept_offer(offer)

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        self.assertEqual(sender_inventory.copper, 5)
        self.assertEqual(recipient_inventory.copper, 0)

    def test_created_offer_is_rejected_after_sender_leaves_room(self) -> None:
        self.cog.inventory_service.grant_currency(self.sender, copper=5)
        offer = self.cog.create_offer(
            7,
            self.recipient.character_id,
            copper=1,
        )

        self.world.place_character(self.sender.character_id, "cellar")

        with self.assertRaisesRegex(ValueError, "room"):
            self.cog.accept_offer(offer)

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        self.assertEqual(sender_inventory.copper, 5)
        self.assertEqual(recipient_inventory.copper, 0)

    def test_sender_can_cancel_the_latest_persisted_request(self) -> None:
        self.cog.inventory_service.grant_currency(self.sender, copper=1)
        offer = self.cog.create_offer(
            7, self.recipient.character_id, copper=1
        )
        request_id = self.cog.create_request(offer)

        self.assertTrue(self.cog.request_is_pending(request_id))
        self.assertTrue(
            asyncio.run(
                self.cog.cancel_request(SimpleNamespace(), 7)
            )
        )
        self.assertFalse(self.cog.request_is_pending(request_id))
        self.assertFalse(
            asyncio.run(self.cog.cancel_request(SimpleNamespace(), 7))
        )

    def test_accept_item_moves_stack_between_characters(self) -> None:
        instance_id = self.cog.inventory_service.grant(
            self.sender,
            "health_potion",
            3,
        )

        result = self.cog.accept_offer(
            GiveOffer(
                sender_user_id=7,
                recipient_user_id=8,
                item_instance_id=instance_id,
                quantity=2,
            )
        )

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        sender_potion = next(
            item
            for item in sender_inventory.items
            if item.template_id == "health_potion"
        )
        recipient_potion = next(
            item
            for item in recipient_inventory.items
            if item.template_id == "health_potion"
        )

        self.assertEqual(sender_potion.quantity, 1)
        self.assertEqual(recipient_potion.quantity, 2)
        self.assertIn("2× Health Potion", result)

    def test_item_offer_is_revalidated_when_accepted(self) -> None:
        instance_id = self.cog.inventory_service.grant(
            self.sender,
            "health_potion",
            1,
        )
        with self.database._connect() as connection:
            connection.execute(
                "DELETE FROM character_items WHERE instance_id = ?",
                (instance_id,),
            )

        with self.assertRaises((InventoryError, KeyError, ValueError)):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=8,
                    item_instance_id=instance_id,
                    quantity=1,
                )
            )

        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )
        self.assertFalse(
            any(
                item.template_id == "health_potion"
                for item in recipient_inventory.items
            )
        )

    def test_accept_currency_moves_each_denomination(self) -> None:
        self.cog.inventory_service.grant_currency(
            self.sender,
            copper=20,
            silver=10,
            gold=5,
        )

        self.cog.accept_offer(
            GiveOffer(
                sender_user_id=7,
                recipient_user_id=8,
                copper=7,
                silver=3,
                gold=2,
            )
        )

        sender_inventory = self.database.get_character_inventory(
            self.sender.character_id
        )
        recipient_inventory = self.database.get_character_inventory(
            self.recipient.character_id
        )

        self.assertEqual(
            (
                sender_inventory.copper,
                sender_inventory.silver,
                sender_inventory.gold,
            ),
            (13, 7, 3),
        )
        self.assertEqual(
            (
                recipient_inventory.copper,
                recipient_inventory.silver,
                recipient_inventory.gold,
            ),
            (7, 3, 2),
        )

    def test_cannot_give_to_self(self) -> None:
        with self.assertRaisesRegex(ValueError, "yourself"):
            self.cog.accept_offer(
                GiveOffer(
                    sender_user_id=7,
                    recipient_user_id=7,
                    copper=1,
                )
            )
