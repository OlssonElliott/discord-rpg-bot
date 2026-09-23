"""Discord UI for player-to-player transfer setup and requests."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from ...database import CharacterNotFoundError
from ...inventory.service import InventoryError
from .models import GiveOffer, RoomRecipient

if TYPE_CHECKING:
    from .cog import GiveCommands


LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 5 * 60


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
