"""Discord UI for character-sheet actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .cog import CharacterCommands


class CharacterSheetView(discord.ui.View):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        character_id: int,
    ) -> None:
        super().__init__(timeout=15 * 60)
        self.cog = cog
        self.user_id = user_id
        self.character_id = character_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the character's player can publish this sheet.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Inventory",
        style=discord.ButtonStyle.secondary,
        emoji="🎒",
    )
    async def inventory(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        from ..inventory import show_inventory

        character = self.cog.database.get_character_by_id(
            self.user_id,
            self.character_id,
        )
        if character is None:
            await interaction.response.send_message(
                "That character is no longer available.",
                ephemeral=True,
            )
            return
        await show_inventory(
            interaction,
            self.cog.inventory_service,
            character,
            edit=True,
        )

    @discord.ui.button(
        label="Publish here",
        style=discord.ButtonStyle.primary,
        emoji="📋",
    )
    async def publish_here(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        del button
        await self.cog.publish_character_sheet(
            interaction,
            self.user_id,
            self.character_id,
        )
