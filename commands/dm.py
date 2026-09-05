"""DM-only character management commands."""

import discord
from discord import app_commands
from discord.ext import commands

from checks import dm_only
from database import (
    CharacterAlreadyExistsError,
    CharacterNotFoundError,
    Database,
    InvalidHitPointsError,
)
from models import Character, Stance


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

    @app_commands.command(name="createcharacter", description="Create a character for a user.")
    @app_commands.describe(user="Discord user", name="Character name", max_hp="Maximum HP")
    @dm_only()
    async def create_character(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        name: str,
        max_hp: int,
    ) -> None:
        try:
            character = self.database.create_character(user.id, name, max_hp)
        except (CharacterAlreadyExistsError, InvalidHitPointsError, ValueError) as error:
            await send_error(interaction, error)
            return
        await interaction.response.send_message(
            embed=result_embed(f"Created {character.name}", character)
        )

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
