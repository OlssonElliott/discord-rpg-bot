"""DM-only character management commands."""

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import dm_only
from ..database import (
    CharacterNotFoundError,
    Database,
    InvalidHitPointsError,
)
from ..models import Character, Stance
from ..inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ..inventory_service import InventoryError, InventoryService
from .inventory import refresh_open_inventory


def result_embed(title: str, character: Character) -> discord.Embed:
    embed = discord.Embed(title=title, colour=discord.Colour.green())
    embed.add_field(name="Character", value=character.name, inline=False)
    embed.add_field(name="HP", value=f"{character.hp}/{character.max_hp}", inline=True)
    embed.add_field(name="Stance", value=character.stance.display_name, inline=True)
    return embed


async def send_error(interaction: discord.Interaction, error: ValueError) -> None:
    await interaction.response.send_message(str(error), ephemeral=True)


class DMCommands(commands.Cog):
    def __init__(self, database: Database) -> None:
        self.database = database
        self.item_catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.inventory_service = InventoryService(database, self.item_catalog)

    async def item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        del interaction
        query = current.casefold().strip()
        return [
            app_commands.Choice(name=template.name, value=template.template_id)
            for template in self.item_catalog.all()
            if not query
            or query in template.name.casefold()
            or query in template.template_id.casefold()
        ][:25]

    @app_commands.command(name="giveitem", description="Give an item to a character.")
    @app_commands.describe(user="Discord user", item="Item", quantity="Stack quantity")
    @app_commands.autocomplete(item=item_autocomplete)
    @dm_only()
    async def give_item(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        item: str,
        quantity: app_commands.Range[int, 1, 99] = 1,
    ) -> None:
        character = self.database.get_character(user.id)
        if character is None:
            await send_error(
                interaction,
                CharacterNotFoundError("That Discord user does not have an active character."),
            )
            return
        try:
            self.inventory_service.grant(character, item, quantity)
            template = self.item_catalog.get(item)
        except (InventoryError, ValueError) as error:
            await send_error(interaction, error)
            return
        quantity_text = f" ×{quantity}" if quantity > 1 else ""
        await interaction.response.send_message(
            f"Gave **{template.name}{quantity_text}** to **{character.name}**.",
            ephemeral=True,
        )
        assert character.character_id is not None
        await refresh_open_inventory(user.id, character.character_id)

    @app_commands.command(name="givecoins", description="Give coins to a character.")
    @app_commands.describe(
        user="Discord user",
        copper="Copper coins",
        silver="Silver coins",
        gold="Gold coins",
    )
    @dm_only()
    async def give_coins(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        copper: app_commands.Range[int, 0, 9999] = 0,
        silver: app_commands.Range[int, 0, 9999] = 0,
        gold: app_commands.Range[int, 0, 9999] = 0,
    ) -> None:
        character = self.database.get_character(user.id)
        if character is None:
            await send_error(
                interaction,
                CharacterNotFoundError(
                    "That Discord user does not have an active character."
                ),
            )
            return
        try:
            wallet = self.inventory_service.grant_currency(
                character,
                copper=copper,
                silver=silver,
                gold=gold,
            )
        except InventoryError as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            f"Gave coins to **{character.name}**. Wallet: "
            f"**{wallet.gold} gold • {wallet.silver} silver • "
            f"{wallet.copper} copper**.",
            ephemeral=True,
        )
        assert character.character_id is not None
        await refresh_open_inventory(user.id, character.character_id)

    @app_commands.command(name="damage", description="Damage a user's character.")
    @app_commands.describe(user="Discord user", amount="Amount of damage")
    @dm_only()
    async def damage(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ) -> None:
        try:
            character = self.database.damage(user.id, amount)
        except (CharacterNotFoundError, InvalidHitPointsError) as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            embed=result_embed(f"{character.name} took {amount} damage", character)
        )

    @app_commands.command(name="heal", description="Heal a user's character.")
    @app_commands.describe(user="Discord user", amount="Amount to heal")
    @dm_only()
    async def heal(
        self, interaction: discord.Interaction, user: discord.Member, amount: int
    ) -> None:
        try:
            character = self.database.heal(user.id, amount)
        except (CharacterNotFoundError, InvalidHitPointsError) as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            embed=result_embed(f"{character.name} healed {amount} HP", character)
        )

    @app_commands.command(name="stance", description="Set a character's stance.")
    @app_commands.describe(user="Discord user", stance="New stance")
    @dm_only()
    async def stance(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        stance: Stance,
    ) -> None:
        try:
            character = self.database.set_stance(user.id, stance)
        except CharacterNotFoundError as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            embed=result_embed(f"Updated {character.name}'s stance", character)
        )

    @app_commands.command(name="sethp", description="Set a character's current HP.")
    @app_commands.describe(user="Discord user", hp="New current HP")
    @dm_only()
    async def set_hp(
        self, interaction: discord.Interaction, user: discord.Member, hp: int
    ) -> None:
        try:
            character = self.database.set_hp(user.id, hp)
        except (CharacterNotFoundError, InvalidHitPointsError) as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            embed=result_embed(f"Updated {character.name}'s HP", character)
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DMCommands(bot.database))
