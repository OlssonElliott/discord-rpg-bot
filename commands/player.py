"""Player-facing slash commands."""

import discord
from discord import app_commands
from discord.ext import commands

from checks import is_dm
from database import Database
from dice import DiceExpressionError, roll
from models import Character


def character_status_embed(character: Character) -> discord.Embed:
    embed = discord.Embed(title=character.name, colour=discord.Colour.blurple())
    embed.add_field(name="HP", value=f"{character.hp}/{character.max_hp}", inline=True)
    embed.add_field(name="Stance", value=character.stance.display_name, inline=True)
    return embed


class PlayerCommands(commands.Cog):
    def __init__(self, database: Database) -> None:
        self.database = database

    @app_commands.command(name="roll", description="Roll dice for your character.")
    @app_commands.describe(expression="Dice notation, for example 1d20+4 or 2d6")
    async def roll_command(self, interaction: discord.Interaction, expression: str) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None and not is_dm(interaction):
            await interaction.response.send_message(
                "You do not have a character yet. Ask your DM to use `/createcharacter`.",
                ephemeral=True,
            )
            return

        try:
            result = roll(expression)
        except DiceExpressionError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        dice_values = ", ".join(str(value) for value in result.results)
        embed = discord.Embed(
            title=f"{character.name} — Dice Roll" if character else "DM Roll",
            colour=discord.Colour.gold(),
        )
        embed.add_field(name="Expression", value=f"`{result.expression}`", inline=False)
        embed.add_field(
            name=f"{result.count}d{result.sides}", value=dice_values, inline=True
        )
        embed.add_field(name="Modifier", value=f"{result.modifier:+d}", inline=True)
        embed.add_field(name="Total", value=f"**{result.total}**", inline=True)
        if character is not None:
            embed.add_field(
                name="HP", value=f"{character.hp}/{character.max_hp}", inline=True
            )
            embed.add_field(
                name="Stance", value=character.stance.display_name, inline=True
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="status", description="Show your character's current status.")
    async def status(self, interaction: discord.Interaction) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None:
            await interaction.response.send_message(
                "You do not have a character yet. Ask your DM to use `/createcharacter`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=character_status_embed(character))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PlayerCommands(bot.database))
