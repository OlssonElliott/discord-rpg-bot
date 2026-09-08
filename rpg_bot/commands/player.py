"""Player-facing slash commands."""

import asyncio
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import is_dm
from ..database import Database
from ..dice import DiceExpressionError, roll
from ..dice_audio import DiceSoundManager
from ..dice_visuals import (
    D20AnimationRenderer,
    InvalidDiceColorError,
    MAX_VISUAL_DICE_COUNT,
    SUPPORTED_VISUAL_DICE,
)
from ..models import Character
from ..portraits import (
    CharacterPortraitStore,
    DEFAULT_DM_PORTRAIT_KEY,
)


LOGGER = logging.getLogger(__name__)

ADVANTAGE_GLOW_COLOR = "#2ECC71"
DISADVANTAGE_GLOW_COLOR = "#E74C3C"

COLOR_SUGGESTIONS = (
    ("Rollkeeper Gold", "#C89B3C"),
    ("Royal Purple", "#7A2EFF"),
    ("Crimson", "#DC143C"),
    ("Ruby", "#E63946"),
    ("Sky Blue", "#00BFFF"),
    ("Emerald", "#2ECC71"),
    ("Teal", "#00BFA6"),
    ("Orange", "#FF8C00"),
    ("Rose", "#FF69B4"),
    ("Ice", "#AEEBFF"),
    ("White", "#F5F5F5"),
    ("Charcoal", "#303030"),
    ("Near Black", "#101010"),
)


def dice_glow_colors(
    sides: int, results: tuple[int, ...], mode: str
) -> tuple[str | None, ...]:
    mode_glow = {
        "advantage": ADVANTAGE_GLOW_COLOR,
        "disadvantage": DISADVANTAGE_GLOW_COLOR,
    }.get(mode)
    return tuple(
        ADVANTAGE_GLOW_COLOR
        if sides == 20 and result == 20
        else DISADVANTAGE_GLOW_COLOR
        if sides == 20 and result == 1
        else mode_glow
        for result in results
    )


async def dice_color_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    del interaction
    query = current.casefold().strip()
    return [
        app_commands.Choice(name=f"{name} — {value}", value=value)
        for name, value in COLOR_SUGGESTIONS
        if not query or query in name.casefold() or query in value.casefold()
    ][:25]


def character_status_embed(character: Character) -> discord.Embed:
    embed = discord.Embed(title=character.name, colour=discord.Colour.blurple())
    embed.add_field(name="HP", value=f"{character.hp}/{character.max_hp}", inline=True)
    embed.add_field(name="Stance", value=character.stance.display_name, inline=True)
    return embed


def apply_character_identity(
    embed: discord.Embed,
    character: Character | None,
    portrait_store: CharacterPortraitStore,
    dm_portrait_key: str | None = None,
) -> Path | None:
    if character is None:
        path = portrait_store.path_for(dm_portrait_key)
        if path is None:
            path = portrait_store.path_for(DEFAULT_DM_PORTRAIT_KEY)
        name = "Dungeon Master"
    else:
        path = portrait_store.path_for(character.portrait_key)
        name = character.name
    embed.set_author(name=name)
    if path is not None:
        embed.set_thumbnail(url=f"attachment://{portrait_attachment_name(path)}")
    return path


def portrait_attachment_name(path: Path) -> str:
    return f"character_portrait{path.suffix.lower()}"


class PlayerCommands(commands.Cog):
    def __init__(
        self,
        database: Database,
        animation_renderer: D20AnimationRenderer | None = None,
        dice_sound_manager: DiceSoundManager | None = None,
        portrait_store: CharacterPortraitStore | None = None,
    ) -> None:
        self.database = database
        self.animation_renderer = animation_renderer or D20AnimationRenderer()
        self.dice_sound_manager = dice_sound_manager or DiceSoundManager()
        self.portrait_store = portrait_store or CharacterPortraitStore()

    @app_commands.command(name="roll", description="Roll dice for your character.")
    @app_commands.describe(
        expression="Dice notation, for example 1d20+4 or 2d6",
        mode="Normal roll, advantage, or disadvantage",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Normal", value="normal"),
            app_commands.Choice(name="Advantage", value="advantage"),
            app_commands.Choice(name="Disadvantage", value="disadvantage"),
        ]
    )
    async def roll_command(
        self,
        interaction: discord.Interaction,
        expression: str,
        mode: str = "normal",
    ) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None and not is_dm(interaction):
            await interaction.response.send_message(
                "You do not have an active character. Use `/character manage` "
                "to equip one or `/character create` to make one.",
                ephemeral=True,
            )
            return

        mode = mode.strip().lower()
        try:
            result = roll(expression, mode=mode)
        except DiceExpressionError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        kept_index = (
            result.results.index(result.kept_result)
            if result.kept_result is not None
            else None
        )
        dice_values = ", ".join(
            f"**{value}** ✓" if index == kept_index else str(value)
            for index, value in enumerate(result.results)
        )
        embed_color = {
            "advantage": discord.Colour(0x2ECC71),
            "disadvantage": discord.Colour(0xE74C3C),
        }.get(mode, discord.Colour.gold())
        embed = discord.Embed(
            title=None if character else "DM Roll",
            colour=embed_color,
        )
        embed.add_field(name="Expression", value=f"`{result.expression}`", inline=False)
        if mode == "advantage":
            embed.add_field(
                name="🟢 Advantage",
                value="Rolling twice and keeping the highest result.",
                inline=False,
            )
        elif mode == "disadvantage":
            embed.add_field(
                name="🔴 Disadvantage",
                value="Rolling twice and keeping the lowest result.",
                inline=False,
            )
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
        dm_portrait_key = None
        if character is None:
            stored_dm_portrait = self.database.get_dm_portrait(interaction.user.id)
            if isinstance(stored_dm_portrait, str):
                dm_portrait_key = stored_dm_portrait
        portrait_path = apply_character_identity(
            embed, character, self.portrait_store, dm_portrait_key
        )
        if (
            result.sides not in SUPPORTED_VISUAL_DICE
            or result.count > MAX_VISUAL_DICE_COUNT
        ):
            if portrait_path is None:
                await interaction.response.send_message(embed=embed)
            else:
                portrait_file = discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
                try:
                    await interaction.response.send_message(
                        embed=embed, file=portrait_file
                    )
                finally:
                    portrait_file.close()
            return

        master_assets = tuple(
            self.animation_renderer.resolve_master(value, result.sides)
            for value in result.results
        )
        if any(asset is None for asset in master_assets):
            if portrait_path is None:
                await interaction.response.send_message(embed=embed)
            else:
                portrait_file = discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
                try:
                    await interaction.response.send_message(
                        embed=embed, file=portrait_file
                    )
                finally:
                    portrait_file.close()
            return

        await interaction.response.defer(thinking=True)
        color = self.database.get_dice_color(interaction.user.id)
        edge_color = self.database.get_dice_edge_color(interaction.user.id)
        number_color = self.database.get_dice_number_color(interaction.user.id)
        glow_colors = dice_glow_colors(result.sides, result.results, mode)
        try:
            if result.count == 1:
                render_arguments = (
                    result.results[0],
                    color,
                    master_assets[0],
                    edge_color,
                    number_color,
                    result.sides,
                )
                if glow_colors[0] is None:
                    animation = await asyncio.to_thread(
                        self.animation_renderer.render, *render_arguments
                    )
                else:
                    animation = await asyncio.to_thread(
                        self.animation_renderer.render,
                        *render_arguments,
                        glow_color=glow_colors[0],
                    )
            else:
                animation = await asyncio.to_thread(
                    self.animation_renderer.render_many,
                    result.results,
                    color,
                    master_assets,
                    edge_color,
                    number_color,
                    result.sides,
                    kept_index,
                    glow_colors=glow_colors,
                )
        except Exception:
            LOGGER.warning("Could not process dice animation", exc_info=True)
            animation = None
        if animation is None:
            portrait_file = (
                discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
                if portrait_path is not None
                else None
            )
            try:
                await interaction.edit_original_response(
                    embed=embed,
                    attachments=[portrait_file] if portrait_file is not None else [],
                )
            finally:
                if portrait_file is not None:
                    portrait_file.close()
            return

        voice_client = await self.dice_sound_manager.prepare(interaction)
        animation_file: discord.File | None = None
        result_slug = "-".join(str(value) for value in result.results)
        try:
            animation_file = discord.File(
                animation.path,
                filename=f"d{result.sides}_{result_slug}.gif",
            )
            await interaction.edit_original_response(
                content=(
                    f"Rolling {result.expression} with {mode}…"
                    if mode != "normal"
                    else f"Rolling {result.expression}…"
                ),
                embed=None,
                attachments=[animation_file],
            )
            self.dice_sound_manager.play_spin(
                voice_client,
                animation.duration_seconds,
            )
        except (discord.HTTPException, OSError):
            LOGGER.warning("Could not send generated dice animation", exc_info=True)
            fallback_portrait = (
                discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
                if portrait_path is not None
                else None
            )
            try:
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    attachments=(
                        [fallback_portrait] if fallback_portrait is not None else []
                    ),
                )
            finally:
                if fallback_portrait is not None:
                    fallback_portrait.close()
            return
        finally:
            if animation_file is not None:
                animation_file.close()

        await asyncio.sleep(max(0.0, animation.duration_seconds - 0.05))
        result_filename = (
            f"d{result.sides}_{result_slug}_result.png"
            if result.count == 1
            else f"d{result.sides}_{result_slug}_results.png"
        )
        result_embed = embed.copy()
        result_embed.set_image(url=f"attachment://{result_filename}")
        result_image_file: discord.File | None = None
        portrait_file: discord.File | None = None
        try:
            result_image_file = discord.File(
                animation.result_image_path,
                filename=result_filename,
            )
            if portrait_path is not None:
                portrait_file = discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
            # Queue the finish sound before the HTTP edit so Discord's voice
            # buffer and message update happen in parallel. Starting it after
            # the edit makes settle audibly trail the visual transition.
            self.dice_sound_manager.play_result(
                voice_client,
                result.sides,
                result.results,
                result.kept_result,
            )
            await interaction.edit_original_response(
                content=None,
                embed=result_embed,
                attachments=[
                    file
                    for file in (result_image_file, portrait_file)
                    if file is not None
                ],
            )
        except (discord.HTTPException, OSError):
            LOGGER.warning("Could not send dice result thumbnail", exc_info=True)
            fallback_portrait = (
                discord.File(
                    portrait_path, filename=portrait_attachment_name(portrait_path)
                )
                if portrait_path is not None
                else None
            )
            try:
                await interaction.edit_original_response(
                    content=None,
                    embed=embed,
                    attachments=(
                        [fallback_portrait] if fallback_portrait is not None else []
                    ),
                )
            finally:
                if fallback_portrait is not None:
                    fallback_portrait.close()
        finally:
            if result_image_file is not None:
                result_image_file.close()
            if portrait_file is not None:
                portrait_file.close()

    @app_commands.command(
        name="dicecolor", description="View or change your animated dice color."
    )
    @app_commands.describe(color="Six-digit hexadecimal color, for example #7A2EFF")
    @app_commands.autocomplete(color=dice_color_autocomplete)
    async def dice_color(
        self, interaction: discord.Interaction, color: str | None = None
    ) -> None:
        if color is None:
            normalized_color = self.database.get_dice_color(interaction.user.id)
            title = "Your Dice Color"
        else:
            try:
                normalized_color = self.database.set_dice_color(interaction.user.id, color)
            except InvalidDiceColorError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            title = "Dice Color Updated"

        embed = discord.Embed(
            title=title,
            description=f"Your dice color is `{normalized_color}`.",
            colour=discord.Colour(int(normalized_color[1:], 16)),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="diceedgecolor", description="View or change your dice edge color."
    )
    @app_commands.describe(color="Six-digit hexadecimal color, for example #FFD700")
    @app_commands.autocomplete(color=dice_color_autocomplete)
    async def dice_edge_color(
        self, interaction: discord.Interaction, color: str | None = None
    ) -> None:
        if color is None:
            normalized_color = self.database.get_dice_edge_color(interaction.user.id)
            title = "Your Dice Edge Color"
        else:
            try:
                normalized_color = self.database.set_dice_edge_color(
                    interaction.user.id, color
                )
            except InvalidDiceColorError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            title = "Dice Edge Color Updated"

        embed = discord.Embed(
            title=title,
            description=f"Your dice edge color is `{normalized_color}`.",
            colour=discord.Colour(int(normalized_color[1:], 16)),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="dicenumbercolor", description="View or change your dice number color."
    )
    @app_commands.describe(color="Six-digit hexadecimal color, for example #F5F5F5")
    @app_commands.autocomplete(color=dice_color_autocomplete)
    async def dice_number_color(
        self, interaction: discord.Interaction, color: str | None = None
    ) -> None:
        if color is None:
            normalized_color = self.database.get_dice_number_color(
                interaction.user.id
            )
            title = "Your Dice Number Color"
        else:
            try:
                normalized_color = self.database.set_dice_number_color(
                    interaction.user.id, color
                )
            except InvalidDiceColorError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            title = "Dice Number Color Updated"

        embed = discord.Embed(
            title=title,
            description=f"Your dice number color is `{normalized_color}`.",
            colour=discord.Colour(int(normalized_color[1:], 16)),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="Show your character's current status.")
    async def status(self, interaction: discord.Interaction) -> None:
        character = self.database.get_character(interaction.user.id)
        if character is None:
            await interaction.response.send_message(
                "You do not have an active character. Use `/character manage` "
                "to equip one or `/character create` to make one.",
                ephemeral=True,
            )
            return
        embed = character_status_embed(character)
        portrait_path = self.portrait_store.path_for(character.portrait_key)
        if portrait_path is None:
            await interaction.response.send_message(embed=embed)
            return
        filename = portrait_attachment_name(portrait_path)
        embed.set_thumbnail(url=f"attachment://{filename}")
        portrait_file = discord.File(
            portrait_path, filename=filename
        )
        try:
            await interaction.response.send_message(embed=embed, file=portrait_file)
        finally:
            portrait_file.close()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        PlayerCommands(
            bot.database,
            D20AnimationRenderer(theme=bot.config.dice_theme),
            DiceSoundManager(),
            CharacterPortraitStore(
                getattr(bot.config, "character_media_path", "data/characters")
            ),
        )
    )
