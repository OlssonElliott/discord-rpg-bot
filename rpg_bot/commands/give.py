"""Player-to-player item and currency transfer commands."""

from __future__ import annotations

from dataclasses import dataclass
import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..database import CharacterNotFoundError, Database
from ..inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ..inventory_service import InventoryError, InventoryService


LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 5 * 60
ROLLKEEPER_NAME = "rollkeeper"


@dataclass(frozen=True)
class GiveOffer:
    sender_user_id: int
    recipient_user_id: int
    sender_character_id: int | None = None
    recipient_character_id: int | None = None
    item_instance_id: str | None = None
    quantity: int = 0
    copper: int = 0
    silver: int = 0
    gold: int = 0

    @property
    def is_item(self) -> bool:
        return self.item_instance_id is not None


@dataclass(frozen=True)
class RoomRecipient:
    user_id: int
    character_id: int
    name: str


class GiveRequestView(discord.ui.View):
    def __init__(
        self,
        cog: GiveCommands,
        offer: GiveOffer,
        *,
        description: str,
        request_id: int | None = None,
    ) -> None:
        super().__init__(timeout=REQUEST_TIMEOUT_SECONDS)
        self.cog = cog
        self.offer = offer
        self.description = description
        self.request_id = request_id
        self.message: discord.Message | None = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.offer.recipient_user_id:
            return True
        await interaction.response.send_message(
            "This transfer request belongs to another player.",
            ephemeral=True,
        )
        return False

    def disable_components(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def resolve_message(
        self,
        interaction: discord.Interaction,
        content: str,
    ) -> None:
        self.resolved = True
        self.disable_components()
        self.stop()
        await interaction.response.edit_message(content=content, view=self)

    async def on_timeout(self) -> None:
        if self.resolved:
            return
        self.disable_components()
        if self.request_id is not None:
            self.cog.finish_request(self.request_id, "expired")
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"Transfer request expired: {self.description}",
                    view=self,
                )
            except discord.HTTPException:
                LOGGER.debug("Could not edit expired give request.", exc_info=True)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.resolved:
            await interaction.response.send_message(
                "This transfer request has already been resolved.",
                ephemeral=True,
            )
            return

        try:
            if self.request_id is not None and not self.cog.request_is_pending(self.request_id):
                await self.resolve_message(interaction, "Transfer request is no longer active.")
                return
            result = self.cog.accept_offer(self.offer)
            if self.request_id is not None:
                self.cog.finish_request(self.request_id, "accepted")
                await self.cog.update_sender_request_message(
                    interaction.client, self.request_id, result
                )
        except (InventoryError, ValueError, CharacterNotFoundError) as error:
            await self.resolve_message(
                interaction,
                f"Transfer failed: {error}",
            )
            return

        await self.resolve_message(interaction, result)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.resolved:
            await interaction.response.send_message(
                "This transfer request has already been resolved.",
                ephemeral=True,
            )
            return

        if self.request_id is not None:
            self.cog.finish_request(self.request_id, "declined")
            await self.cog.update_sender_request_message(
                interaction.client, self.request_id,
                f"Transfer request declined: {self.description}",
            )
        await self.resolve_message(
            interaction,
            f"Declined: {self.description}",
        )


class GiveRecipientSelect(discord.ui.Select):
    def __init__(
        self,
        owner: GiveSetupView,
        recipients: tuple[RoomRecipient, ...],
    ) -> None:
        self.owner = owner
        super().__init__(
            placeholder="Choose a character in your room",
            options=[
                discord.SelectOption(
                    label=recipient.name[:100],
                    value=str(recipient.character_id),
                )
                for recipient in recipients[:25]
            ],
            custom_id="give:recipient",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner.recipient_character_id = int(self.values[0])
        self.owner.confirm_button.disabled = not self.owner.ready
        await interaction.response.edit_message(view=self.owner)


class GiveItemSelect(discord.ui.Select):
    def __init__(
        self,
        owner: GiveSetupView,
        items: tuple[tuple[str, str], ...],
    ) -> None:
        self.owner = owner
        super().__init__(
            placeholder="Choose an item from your inventory",
            options=[
                discord.SelectOption(label=label[:100], value=instance_id)
                for instance_id, label in items[:25]
            ],
            custom_id="give:item",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.owner.item_instance_id = self.values[0]
        self.owner.quantity = 1
        self.owner.quantity_button.disabled = False
        self.owner.confirm_button.disabled = not self.owner.ready
        await interaction.response.edit_message(view=self.owner)


class GiveQuantityModal(discord.ui.Modal, title="Item quantity"):
    quantity_input = discord.ui.TextInput(
        label="Quantity",
        default="1",
        required=True,
        max_length=3,
    )

    def __init__(self, owner: GiveSetupView) -> None:
        super().__init__()
        self.owner = owner
        self.quantity_input.default = str(owner.quantity)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            quantity = int(str(self.quantity_input.value).strip())
            if quantity < 1:
                raise ValueError
            sender = self.owner.cog._character(self.owner.sender_user_id)
            if sender.character_id is None:
                raise ValueError("You need an active character.")
            item = self.owner.cog._owned_item(
                self.owner.cog.database.get_character_inventory(sender.character_id),
                self.owner.item_instance_id,
            )
            if quantity > item.quantity:
                raise ValueError(f"You only have {item.quantity} of that item.")
        except ValueError as error:
            message = str(error) or "Enter a whole number of at least 1."
            await interaction.response.send_message(message, ephemeral=True)
            return

        self.owner.quantity = quantity
        await interaction.response.send_message(
            f"Quantity set to {quantity}.", ephemeral=True
        )


class GiveCoinsModal(discord.ui.Modal, title="Give coins"):
    copper_input = discord.ui.TextInput(
        label="Copper",
        default="0",
        required=False,
        max_length=6,
    )
    silver_input = discord.ui.TextInput(
        label="Silver",
        default="0",
        required=False,
        max_length=6,
    )
    gold_input = discord.ui.TextInput(
        label="Gold",
        default="0",
        required=False,
        max_length=6,
    )

    def __init__(self, owner: GiveSetupView) -> None:
        super().__init__()
        self.owner = owner

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if self.owner.recipient_character_id is None:
            await interaction.response.send_message(
                "Choose a recipient first.", ephemeral=True
            )
            return
        try:
            amounts = tuple(
                int(str(field.value or "0").strip())
                for field in (
                    self.copper_input,
                    self.silver_input,
                    self.gold_input,
                )
            )
            if min(amounts) < 0 or not any(amounts):
                raise ValueError("Enter at least one non-negative coin amount.")
            offer = self.owner.cog.create_offer(
                self.owner.sender_user_id,
                self.owner.recipient_character_id,
                copper=amounts[0],
                silver=amounts[1],
                gold=amounts[2],
            )
            recipient_user, request_id = await self.owner.cog.send_offer_request(
                interaction.client,
                offer,
            )
        except (InventoryError, ValueError, CharacterNotFoundError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        self.owner.stop()
        sender_view = GiveCancelView(
            self.owner.cog, self.owner.sender_user_id, request_id
        )
        if self.owner.message is not None:
            self.owner.cog.set_sender_message(request_id, self.owner.message)
            await self.owner.message.edit(
                content=(
                    f"Transfer request sent to {recipient_user.mention}. "
                    "Nothing will leave your inventory until they accept."
                ),
                view=sender_view,
            )
        await interaction.response.send_message(
            f"Transfer request sent to {recipient_user.mention}. "
            "Nothing will leave your inventory until they accept.",
            ephemeral=True,
        )


class GiveCancelView(discord.ui.View):
    def __init__(self, cog: GiveCommands, sender_user_id: int, request_id: int) -> None:
        super().__init__(timeout=REQUEST_TIMEOUT_SECONDS)
        self.cog = cog
        self.sender_user_id = sender_user_id
        self.request_id = request_id

    @discord.ui.button(label="Cancel request", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        del button
        if interaction.user.id != self.sender_user_id:
            await interaction.response.send_message("This request belongs to another player.", ephemeral=True)
            return
        if not await self.cog.cancel_request(interaction.client, self.sender_user_id, self.request_id):
            await interaction.response.send_message("This transfer request is no longer active.", ephemeral=True)
            return
        self.cancel.disabled = True
        self.stop()
        await interaction.response.edit_message(content="Transfer request cancelled.", view=self)


class GiveSetupView(discord.ui.View):
    def __init__(
        self,
        cog: GiveCommands,
        sender_user_id: int,
        recipients: tuple[RoomRecipient, ...],
        *,
        items: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(timeout=REQUEST_TIMEOUT_SECONDS)
        self.cog = cog
        self.sender_user_id = sender_user_id
        self.quantity = 1
        self.recipient_character_id: int | None = None
        self.item_instance_id: str | None = None
        self.message: discord.Message | None = None

        self.add_item(GiveRecipientSelect(self, recipients))
        if items:
            self.add_item(GiveItemSelect(self, items))

        self.quantity_button.disabled = True
        self.confirm_button.disabled = True

    @property
    def ready(self) -> bool:
        return self.recipient_character_id is not None and self.item_instance_id is not None

    def disable_components(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.sender_user_id:
            return True
        await interaction.response.send_message(
            "This give menu belongs to another player.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Set item quantity",
        style=discord.ButtonStyle.secondary,
        custom_id="give:quantity",
        row=2,
    )
    async def quantity_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.item_instance_id is None:
            await interaction.response.send_message(
                "Choose an item first.", ephemeral=True
            )
            return
        await interaction.response.send_modal(GiveQuantityModal(self))

    @discord.ui.button(
        label="Give coins",
        style=discord.ButtonStyle.secondary,
        custom_id="give:coins",
        row=2,
    )
    async def coins_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if self.recipient_character_id is None:
            await interaction.response.send_message(
                "Choose a recipient first.", ephemeral=True
            )
            return
        await interaction.response.send_modal(GiveCoinsModal(self))

    @discord.ui.button(
        label="Send transfer request",
        style=discord.ButtonStyle.success,
        custom_id="give:confirm",
        row=2,
    )
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        if not self.ready or self.recipient_character_id is None:
            await interaction.response.send_message(
                "Choose a recipient and item first.",
                ephemeral=True,
            )
            return

        try:
            offer = self.cog.create_offer(
                self.sender_user_id,
                self.recipient_character_id,
                item_instance_id=self.item_instance_id,
                quantity=self.quantity,
            )
            recipient_user, request_id = await self.cog.send_offer_request(
                interaction.client,
                offer,
            )
        except (InventoryError, ValueError, CharacterNotFoundError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        self.stop()
        self.cog.set_sender_message(request_id, interaction.message)
        await interaction.response.edit_message(
            content=(
                f"Transfer request sent to {recipient_user.mention}. "
                "Nothing will leave your inventory until they accept."
            ),
            view=GiveCancelView(self.cog, self.sender_user_id, request_id),
        )


class GiveCommands(commands.Cog):
    def __init__(self, database: Database) -> None:
        self.database = database
        self.catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.inventory_service = InventoryService(database, self.catalog)

    def _character(self, user_id: int):
        return self.database.get_character(user_id)

    @staticmethod
    def _owned_item(inventory, instance_id: str | None):
        item = next(
            (
                carried
                for carried in inventory.items
                if carried.instance_id == instance_id
            ),
            None,
        )
        if item is None:
            raise ValueError("You can only give an item from your own inventory.")
        return item

    def room_recipients(self, sender_user_id: int) -> tuple[RoomRecipient, ...]:
        with self.database._connect() as connection:
            sender_row = connection.execute(
                """
                SELECT id, current_room_id
                FROM characters
                WHERE discord_user_id = ?
                  AND is_active = 1
                  AND is_archived = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (sender_user_id,),
            ).fetchone()
            if sender_row is None or not sender_row["current_room_id"]:
                return ()

            rows = connection.execute(
                """
                SELECT id, discord_user_id, name
                FROM characters
                WHERE current_room_id = ?
                  AND id <> ?
                  AND discord_user_id <> ?
                  AND is_archived = 0
                ORDER BY name COLLATE NOCASE, id
                """,
                (
                    str(sender_row["current_room_id"]),
                    int(sender_row["id"]),
                    sender_user_id,
                ),
            ).fetchall()

            return tuple(
                RoomRecipient(
                    user_id=int(row["discord_user_id"]),
                    character_id=int(row["id"]),
                    name=str(row["name"]),
                )
                for row in rows
                if str(row["name"]).strip().casefold() != ROLLKEEPER_NAME
            )

    def _room_recipient(
        self,
        sender_user_id: int,
        recipient_character_id: int,
    ) -> RoomRecipient:
        recipient = next(
            (
                candidate
                for candidate in self.room_recipients(sender_user_id)
                if candidate.character_id == recipient_character_id
            ),
            None,
        )
        if recipient is None:
            raise ValueError(
                "You can only give items or coins to another character in your room."
            )
        return recipient

    async def player_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            recipients = self.room_recipients(interaction.user.id)
        except CharacterNotFoundError:
            return []

        query = current.strip().casefold()
        return [
            app_commands.Choice(
                name=recipient.name[:100],
                value=str(recipient.character_id),
            )
            for recipient in recipients
            if recipient.name.strip().casefold() != ROLLKEEPER_NAME
            and (not query or query in recipient.name.casefold())
        ][:25]

    async def item_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        try:
            character = self._character(interaction.user.id)
        except CharacterNotFoundError:
            return []

        if character.character_id is None:
            return []

        inventory = self.database.get_character_inventory(character.character_id)
        equipped = set(inventory.equipment.values())
        query = current.strip().casefold()
        choices: list[app_commands.Choice[str]] = []

        for item in inventory.items:
            if item.instance_id in equipped:
                continue

            template = self.catalog.get(item.template_id)
            searchable = f"{template.name} {template.template_id}".casefold()
            if query and query not in searchable:
                continue

            quantity_suffix = (
                f" ×{item.quantity}" if item.quantity > 1 else ""
            )
            choices.append(
                app_commands.Choice(
                    name=f"{template.name}{quantity_suffix}"[:100],
                    value=item.instance_id,
                )
            )
            if len(choices) == 25:
                break

        return choices

    def _remove_inventory_quantity(
        self,
        character_id: int,
        instance_id: str,
        quantity: int,
    ) -> None:
        if quantity <= 0:
            raise ValueError("Quantity must be at least 1.")

        with self.database._connect() as connection:
            row = connection.execute(
                """
                SELECT quantity
                FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            ).fetchone()
            if row is None or int(row["quantity"]) < quantity:
                raise ValueError("The item is no longer available in that quantity.")

            remaining = int(row["quantity"]) - quantity
            if remaining == 0:
                connection.execute(
                    """
                    DELETE FROM character_items
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (character_id, instance_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE character_items
                    SET quantity = ?
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (remaining, character_id, instance_id),
                )

    def give_item_choices(
        self,
        sender_user_id: int,
    ) -> tuple[tuple[str, str], ...]:
        sender = self._character(sender_user_id)
        if sender.character_id is None:
            return ()

        inventory = self.database.get_character_inventory(sender.character_id)
        equipped = set(inventory.equipment.values())
        choices: list[tuple[str, str]] = []
        for item in inventory.items:
            if item.instance_id in equipped:
                continue
            template = self.catalog.get(item.template_id)
            quantity_suffix = f" ×{item.quantity}" if item.quantity > 1 else ""
            choices.append(
                (item.instance_id, f"{template.name}{quantity_suffix}")
            )
        return tuple(choices)

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
        sender = self._character(sender_user_id)
        recipient = self._room_recipient(
            sender_user_id,
            recipient_character_id,
        )
        giving_coins = any((copper, silver, gold))

        if (item_instance_id is None) == (not giving_coins):
            raise ValueError("Choose either one item or coins to give, not both.")
        if sender.character_id is None:
            raise ValueError("You need an active character.")

        inventory = self.database.get_character_inventory(sender.character_id)
        if item_instance_id is not None:
            inventory_item = self._owned_item(inventory, item_instance_id)
            if inventory_item.instance_id in inventory.equipment.values():
                raise ValueError("Unequip that item before giving it away.")
            if inventory_item.quantity < quantity:
                raise ValueError("You do not have that many.")
            return GiveOffer(
                sender_user_id=sender_user_id,
                recipient_user_id=recipient.user_id,
                sender_character_id=sender.character_id,
                recipient_character_id=recipient.character_id,
                item_instance_id=inventory_item.instance_id,
                quantity=quantity,
            )

        if inventory.copper < copper:
            raise ValueError("You do not have enough copper.")
        if inventory.silver < silver:
            raise ValueError("You do not have enough silver.")
        if inventory.gold < gold:
            raise ValueError("You do not have enough gold.")

        return GiveOffer(
            sender_user_id=sender_user_id,
            recipient_user_id=recipient.user_id,
            sender_character_id=sender.character_id,
            recipient_character_id=recipient.character_id,
            copper=copper,
            silver=silver,
            gold=gold,
        )

    def create_request(self, offer: GiveOffer) -> int:
        with self.database._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO give_requests (
                    sender_user_id, recipient_user_id, sender_character_id,
                    recipient_character_id, item_instance_id, quantity,
                    copper, silver, gold
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer.sender_user_id, offer.recipient_user_id,
                    offer.sender_character_id, offer.recipient_character_id,
                    offer.item_instance_id, offer.quantity, offer.copper,
                    offer.silver, offer.gold,
                ),
            )
            return int(cursor.lastrowid)

    def request_is_pending(self, request_id: int) -> bool:
        with self.database._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM give_requests WHERE id = ? AND status = 'pending'",
                (request_id,),
            ).fetchone()
        return row is not None

    def finish_request(self, request_id: int, status: str) -> None:
        with self.database._connect() as connection:
            connection.execute(
                "UPDATE give_requests SET status = ? WHERE id = ? AND status = 'pending'",
                (status, request_id),
            )

    def set_sender_message(self, request_id: int, message) -> None:
        with self.database._connect() as connection:
            connection.execute(
                """UPDATE give_requests SET sender_channel_id = ?, sender_message_id = ?
                WHERE id = ?""",
                (message.channel.id, message.id, request_id),
            )

    async def update_sender_request_message(self, client, request_id: int, content: str) -> None:
        with self.database._connect() as connection:
            row = connection.execute(
                "SELECT sender_channel_id, sender_message_id FROM give_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        if row is None or not row["sender_channel_id"] or not row["sender_message_id"]:
            return
        try:
            channel = client.get_channel(int(row["sender_channel_id"]))
            if channel is None:
                channel = await client.fetch_channel(int(row["sender_channel_id"]))
            message = await channel.fetch_message(int(row["sender_message_id"]))
            await message.edit(content=content, view=None)
        except discord.HTTPException:
            LOGGER.debug("Could not update sender give request.", exc_info=True)

    async def cancel_request(self, client, sender_user_id: int, request_id: int | None = None) -> bool:
        with self.database._connect() as connection:
            if request_id is None:
                row = connection.execute(
                    """SELECT id, recipient_channel_id, recipient_message_id,
                    sender_channel_id, sender_message_id
                    FROM give_requests WHERE sender_user_id = ? AND status = 'pending'
                    ORDER BY id DESC LIMIT 1""",
                    (sender_user_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """SELECT id, recipient_channel_id, recipient_message_id,
                    sender_channel_id, sender_message_id
                    FROM give_requests WHERE id = ? AND sender_user_id = ? AND status = 'pending'""",
                    (request_id, sender_user_id),
                ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE give_requests SET status = 'cancelled' WHERE id = ?",
                (row["id"],),
            )

        if row["recipient_channel_id"] and row["recipient_message_id"]:
            try:
                channel = client.get_channel(int(row["recipient_channel_id"]))
                if channel is None:
                    channel = await client.fetch_channel(int(row["recipient_channel_id"]))
                message = await channel.fetch_message(int(row["recipient_message_id"]))
                await message.edit(content="Transfer request cancelled by sender.", view=None)
            except discord.HTTPException:
                LOGGER.debug("Could not update cancelled give request.", exc_info=True)
        await self.update_sender_request_message(
            client, int(row["id"]), "Transfer request cancelled."
        )
        return True

    async def send_offer_request(
        self,
        client,
        offer: GiveOffer,
    ):
        recipient_user = client.get_user(offer.recipient_user_id)
        if recipient_user is None:
            try:
                recipient_user = await client.fetch_user(offer.recipient_user_id)
            except discord.HTTPException as error:
                raise ValueError(
                    "I couldn't find that player's Discord account."
                ) from error

        description = self.describe_offer(offer)
        request_id = self.create_request(offer)
        view = GiveRequestView(
            self, offer, description=description, request_id=request_id
        )
        try:
            message = await recipient_user.send(
                f"{description}\n\nAccept or decline the transfer below.",
                view=view,
            )
        except discord.HTTPException as error:
            self.finish_request(request_id, "cancelled")
            raise ValueError(
                f"I couldn't send {recipient_user.mention} the transfer request. "
                "They may have direct messages disabled."
            ) from error

        view.message = message
        with self.database._connect() as connection:
            connection.execute(
                """UPDATE give_requests
                SET recipient_channel_id = ?, recipient_message_id = ?
                WHERE id = ?""",
                (message.channel.id, message.id, request_id),
            )
        return recipient_user, request_id

    def describe_offer(self, offer: GiveOffer) -> str:
        sender, _ = self._offer_characters(offer)

        if offer.is_item:
            if sender.character_id is None:
                raise ValueError("The sender has no active character.")
            inventory = self.database.get_character_inventory(sender.character_id)
            item = self._owned_item(inventory, offer.item_instance_id)
            template = self.catalog.get(item.template_id)
            return (
                f"**{sender.name}** wants to give you "
                f"**{offer.quantity}× {template.name}**."
            )

        coins = []
        if offer.gold:
            coins.append(f"{offer.gold} gold")
        if offer.silver:
            coins.append(f"{offer.silver} silver")
        if offer.copper:
            coins.append(f"{offer.copper} copper")
        return f"**{sender.name}** wants to give you **{', '.join(coins)}**."

    def _legacy_recipient_character(self, offer: GiveOffer):
        if offer.sender_user_id == offer.recipient_user_id:
            raise ValueError("You cannot give something to yourself.")

        with self.database._connect() as connection:
            rows = connection.execute(
                """
                SELECT id
                FROM characters
                WHERE discord_user_id = ?
                  AND is_archived = 0
                ORDER BY id
                """,
                (offer.recipient_user_id,),
            ).fetchall()

        if len(rows) != 1:
            raise ValueError("The receiving character is no longer available.")

        return self.database.get_character_by_id(
            offer.recipient_user_id,
            int(rows[0]["id"]),
        )

    def _offer_characters(self, offer: GiveOffer):
        sender = (
            self.database.get_character_by_id(
                offer.sender_user_id,
                offer.sender_character_id,
            )
            if offer.sender_character_id is not None
            else self._character(offer.sender_user_id)
        )
        if sender is None or sender.character_id is None:
            raise ValueError("The sending character is no longer available.")

        if offer.recipient_character_id is not None:
            recipient = self.database.get_character_by_id(
                offer.recipient_user_id,
                offer.recipient_character_id,
            )
        else:
            recipient = self._legacy_recipient_character(offer)

        if recipient is None or recipient.character_id is None:
            raise ValueError("The receiving character is no longer available.")
        if recipient.is_archived:
            raise ValueError("The receiving character is no longer available.")
        if recipient.name.strip().casefold() == ROLLKEEPER_NAME:
            raise ValueError("You cannot give items or coins to Rollkeeper.")
        if sender.discord_user_id == recipient.discord_user_id:
            raise ValueError("You cannot give something to yourself.")
        if (
            not sender.current_room_id
            or not recipient.current_room_id
            or sender.current_room_id != recipient.current_room_id
        ):
            raise ValueError(
                "You can only give items or coins to another character in your room."
            )

        return sender, recipient

    def _accept_item(
        self,
        offer: GiveOffer,
        sender,
        recipient,
    ) -> str:
        if sender.character_id is None or recipient.character_id is None:
            raise ValueError("Both characters must still be available.")

        sender_inventory = self.database.get_character_inventory(sender.character_id)
        item = self._owned_item(sender_inventory, offer.item_instance_id)

        if item.instance_id in sender_inventory.equipment.values():
            raise ValueError("The item is equipped and cannot be given.")
        if offer.quantity <= 0:
            raise ValueError("Quantity must be at least 1.")
        if item.quantity < offer.quantity:
            raise ValueError(
                f"{sender.name} no longer has enough of that item."
            )

        template = self.catalog.get(item.template_id)

        # Grant first so receiver capacity is validated before the sender loses
        # anything. If sender state changes before completion, compensate.
        recipient_instance_id = self.inventory_service.grant(
            recipient,
            item.template_id,
            offer.quantity,
        )

        try:
            refreshed = self.database.get_character_inventory(sender.character_id)
            sender_item = self._owned_item(refreshed, offer.item_instance_id)
            if sender_item.instance_id in refreshed.equipment.values():
                raise ValueError("The item was equipped before the transfer completed.")
            if sender_item.quantity < offer.quantity:
                raise ValueError(
                    f"{sender.name} no longer has enough of that item."
                )

            self._remove_inventory_quantity(
                sender.character_id,
                sender_item.instance_id,
                offer.quantity,
            )
        except Exception:
            self._remove_inventory_quantity(
                recipient.character_id,
                recipient_instance_id,
                offer.quantity,
            )
            raise

        return (
            f"Accepted. **{sender.name}** gave **{recipient.name}** "
            f"**{offer.quantity}× {template.name}**."
        )

    def _accept_currency(
        self,
        offer: GiveOffer,
        sender,
        recipient,
    ) -> str:
        if sender.character_id is None or recipient.character_id is None:
            raise ValueError("Both characters must still be available.")

        if min(offer.copper, offer.silver, offer.gold) < 0:
            raise ValueError("Coin amounts cannot be negative.")
        if not any((offer.copper, offer.silver, offer.gold)):
            raise ValueError("No coins were offered.")

        sender_inventory = self.database.get_character_inventory(sender.character_id)
        if sender_inventory.copper < offer.copper:
            raise ValueError(f"{sender.name} no longer has enough copper.")
        if sender_inventory.silver < offer.silver:
            raise ValueError(f"{sender.name} no longer has enough silver.")
        if sender_inventory.gold < offer.gold:
            raise ValueError(f"{sender.name} no longer has enough gold.")

        self.inventory_service.grant_currency(
            recipient,
            copper=offer.copper,
            silver=offer.silver,
            gold=offer.gold,
        )

        try:
            with self.database._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE character_wallets
                    SET copper = copper - ?,
                        silver = silver - ?,
                        gold = gold - ?
                    WHERE character_id = ?
                      AND copper >= ?
                      AND silver >= ?
                      AND gold >= ?
                    """,
                    (
                        offer.copper,
                        offer.silver,
                        offer.gold,
                        sender.character_id,
                        offer.copper,
                        offer.silver,
                        offer.gold,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"{sender.name}'s coin balance changed before "
                        "the transfer completed."
                    )
        except Exception:
            with self.database._connect() as connection:
                connection.execute(
                    """
                    UPDATE character_wallets
                    SET copper = copper - ?,
                        silver = silver - ?,
                        gold = gold - ?
                    WHERE character_id = ?
                    """,
                    (
                        offer.copper,
                        offer.silver,
                        offer.gold,
                        recipient.character_id,
                    ),
                )
            raise

        coins = []
        if offer.gold:
            coins.append(f"{offer.gold} gold")
        if offer.silver:
            coins.append(f"{offer.silver} silver")
        if offer.copper:
            coins.append(f"{offer.copper} copper")

        return (
            f"Accepted. **{sender.name}** gave **{recipient.name}** "
            f"**{', '.join(coins)}**."
        )

    def accept_offer(self, offer: GiveOffer) -> str:
        sender, recipient = self._offer_characters(offer)
        if offer.is_item:
            return self._accept_item(offer, sender, recipient)
        return self._accept_currency(offer, sender, recipient)

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
