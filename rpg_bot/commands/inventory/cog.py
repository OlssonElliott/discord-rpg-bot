"""Private Discord inventory browser and item actions."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ...inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ...inventory.service import InventoryService
from .presentation import inventory_embed, readable_field_pages
from .views import InventoryItemSelect, InventoryOwnedView, InventoryView
from .runtime import (
    OpenInventory,
    _announce_room_action,
    forget_open_inventory,
    refresh_character_sheet,
    refresh_inventory_views,
    refresh_open_inventory,
    show_inventory,
)


class InventoryCommands(commands.Cog):
    def __init__(self, database, catalog: ItemCatalog | None = None) -> None:
        self.catalog = catalog or ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.service = InventoryService(database, self.catalog)

    @app_commands.command(name="inventory", description="Open your active inventory privately.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        character = self.service.database.get_character(interaction.user.id)
        if character is None or character.character_id is None:
            await interaction.response.send_message(
                "You do not have an active character. Use `/character manage` first.",
                ephemeral=True,
            )
            return
        await show_inventory(interaction, self.service, character)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InventoryCommands(bot.database))
