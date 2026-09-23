"""Player-to-player item and currency transfer commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ...database import CharacterNotFoundError, Database
from ...inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ...inventory.service import InventoryService
from . import offers as give_offer_support
from . import requests as give_request_support
from . import transfers as give_transfer_support
from .models import GiveOffer, RoomRecipient
from .views import (
    REQUEST_TIMEOUT_SECONDS,
    GiveCancelView,
    GiveCoinsModal,
    GiveItemSelect,
    GiveQuantityModal,
    GiveRecipientSelect,
    GiveRequestView,
    GiveSetupView,
)
ROLLKEEPER_NAME = "rollkeeper"


class GiveCommands(commands.Cog):
    def __init__(self, database: Database) -> None:
        self.database = database
        self.catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.inventory_service = InventoryService(database, self.catalog)

    def _character(self, user_id: int):
        return give_offer_support.character(self, user_id)

    @staticmethod
    def _owned_item(inventory, instance_id: str | None):
        return give_offer_support.owned_item(inventory, instance_id)

    def room_recipients(self, sender_user_id: int) -> tuple[RoomRecipient, ...]:
        return give_offer_support.room_recipients(self, sender_user_id)

    def _room_recipient(
        self,
        sender_user_id: int,
        recipient_character_id: int,
    ) -> RoomRecipient:
        return give_offer_support.room_recipient(
            self,
            sender_user_id,
            recipient_character_id,
        )

    async def player_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await give_offer_support.player_autocomplete(
            self,
            interaction,
            current,
        )

    async def item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await give_offer_support.item_autocomplete(
            self,
            interaction,
            current,
        )

    def _remove_inventory_quantity(
        self,
        character_id: int,
        instance_id: str,
        quantity: int,
    ) -> None:
        return give_offer_support.remove_inventory_quantity(
            self,
            character_id,
            instance_id,
            quantity,
        )

    def give_item_choices(
        self,
        sender_user_id: int,
    ) -> tuple[tuple[str, str], ...]:
        return give_offer_support.give_item_choices(
            self,
            sender_user_id,
        )

    def create_offer(
        self,
        sender_user_id: int,
        recipient_character_id: int,
        *,
        item_instance_id: str | None = None,
        quantity: int = 1,
        copper: int = 0,
        silver: int = 0,
        gold: int = 0,
    ) -> GiveOffer:
        return give_offer_support.create_offer(
            self,
            sender_user_id,
            recipient_character_id,
            item_instance_id=item_instance_id,
            quantity=quantity,
            copper=copper,
            silver=silver,
            gold=gold,
        )

    def create_request(self, offer: GiveOffer) -> int:
        return give_request_support.create_request(self, offer)

    def request_is_pending(self, request_id: int) -> bool:
        return give_request_support.request_is_pending(self, request_id)

    def finish_request(self, request_id: int, status: str) -> None:
        return give_request_support.finish_request(self, request_id, status)

    def set_sender_message(self, request_id: int, message) -> None:
        return give_request_support.set_sender_message(self, request_id, message)

    async def update_sender_request_message(
        self, client, request_id: int, content: str
    ) -> None:
        return await give_request_support.update_sender_request_message(
            self,
            client,
            request_id,
            content,
        )

    async def cancel_request(
        self, client, sender_user_id: int, request_id: int | None = None
    ) -> bool:
        return await give_request_support.cancel_request(
            self,
            client,
            sender_user_id,
            request_id,
        )

    async def send_offer_request(
        self,
        client,
        offer: GiveOffer,
    ):
        return await give_request_support.send_offer_request(
            self,
            client,
            offer,
        )

    def describe_offer(self, offer: GiveOffer) -> str:
        return give_transfer_support.describe_offer(self, offer)

    def _legacy_recipient_character(self, offer: GiveOffer):
        return give_transfer_support.legacy_recipient_character(self, offer)

    def _offer_characters(self, offer: GiveOffer):
        return give_transfer_support.offer_characters(self, offer)

    def _accept_item(
        self,
        offer: GiveOffer,
        sender,
        recipient,
    ) -> str:
        return give_transfer_support.accept_item(
            self,
            offer,
            sender,
            recipient,
        )

    def _accept_currency(
        self,
        offer: GiveOffer,
        sender,
        recipient,
    ) -> str:
        return give_transfer_support.accept_currency(
            self,
            offer,
            sender,
            recipient,
        )

    def accept_offer(self, offer: GiveOffer) -> str:
        return give_transfer_support.accept_offer(self, offer)

    cancel = app_commands.Group(
        name="cancel", description="Cancel one of your pending requests."
    )

    @cancel.command(name="give", description="Cancel your latest give request.")
    async def cancel_give(self, interaction: discord.Interaction) -> None:
        if await self.cancel_request(interaction.client, interaction.user.id):
            await interaction.response.send_message(
                "Your latest give request was cancelled.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "You have no pending give request.", ephemeral=True
        )

    @app_commands.command(
        name="give",
        description="Offer an item or coins to another character in your room.",
    )
    async def give(
        self,
        interaction: discord.Interaction,
    ) -> None:
        try:
            sender = self._character(interaction.user.id)
            recipients = self.room_recipients(interaction.user.id)
        except CharacterNotFoundError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        if not recipients:
            await interaction.response.send_message(
                "There are no other player characters in your room.",
                ephemeral=True,
            )
            return

        if sender.character_id is None:
            await interaction.response.send_message(
                "You need an active character.",
                ephemeral=True,
            )
            return

        items = self.give_item_choices(interaction.user.id)

        view = GiveSetupView(
            self,
            interaction.user.id,
            recipients,
            items=items,
        )
        await interaction.response.send_message(
            "Choose a recipient and an item, or use **Give coins**.",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    database = getattr(bot, "database", None)
    if database is None:
        raise RuntimeError("The bot must expose its Database as bot.database.")
    await bot.add_cog(GiveCommands(database))
