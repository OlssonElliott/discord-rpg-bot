"""Discord adapter for the shared landmark-based combat scene."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..checks import dm_only
from ..combat import CombatScene
from ..combat_service import CombatError, CombatService
from ..database import Database
from ..world_service import WorldService


COMBAT_CHANNEL_NAME = "combat"
LOGGER = logging.getLogger(__name__)


def _field_text(lines: list[str], empty: str) -> str:
    text = "\n".join(lines) or empty
    return text if len(text) <= 1024 else f"{text[:1021]}..."


def combat_scene_embed(scene: CombatScene, room_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Combat · {room_name}",
        description=(
            "Landmark-based combat scene. Positions are relative to room landmarks, "
            "not grid squares."
        ),
        colour=discord.Colour.from_rgb(111, 37, 32),
    )
    landmark_names = {landmark.id: landmark.name for landmark in scene.landmarks}
    landmark_lines = []
    for landmark in scene.landmarks:
        suffix = ""
        if landmark.x is not None and landmark.y is not None:
            suffix = f" · {landmark.x:.0%}, {landmark.y:.0%}"
        landmark_lines.append(f"**{landmark.name}**{suffix}")
    embed.add_field(
        name="Landmarks",
        value=_field_text(landmark_lines, "None"),
        inline=False,
    )

    combatant_lines = [
        (
            f"**{combatant.name}** · {combatant.relation.value.replace('_', ' ')} "
            f"{landmark_names.get(combatant.landmark_id, combatant.landmark_id)}"
        )
        for combatant in scene.combatants
    ]
    embed.add_field(
        name="Combatants",
        value=_field_text(combatant_lines, "None"),
        inline=False,
    )

    route_lines = []
    for route in scene.routes:
        details = route.distance.value
        if route.obstacle:
            details += f" · {route.obstacle}"
        if route.blocked:
            details += " · blocked"
        route_lines.append(
            f"{landmark_names.get(route.source_landmark_id, route.source_landmark_id)} "
            f"↔ {landmark_names.get(route.destination_landmark_id, route.destination_landmark_id)} "
            f"· {details}"
        )
    embed.add_field(
        name="Routes",
        value=_field_text(route_lines, "Not arranged yet."),
        inline=False,
    )
    embed.set_footer(text=f"Scene #{scene.id} · room {scene.room_id}")
    return embed


async def ensure_combat_channel(guild):
    """Ensure the guild has one shared public combat channel."""
    for channel in getattr(guild, "text_channels", ()):
        if getattr(channel, "name", "").casefold() == COMBAT_CHANNEL_NAME:
            return channel
    bot_member = getattr(guild, "me", None)
    if (
        bot_member is None
        or not getattr(bot_member.guild_permissions, "manage_channels", False)
    ):
        LOGGER.warning(
            "Could not create #%s in guild %s: Manage Channels is missing",
            COMBAT_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None
    try:
        return await guild.create_text_channel(
            COMBAT_CHANNEL_NAME,
            topic="Shared landmark-based combat scene and turn state.",
            reason="Public Rollkeeper combat channel",
        )
    except discord.HTTPException:
        LOGGER.exception(
            "Could not create #%s in guild %s",
            COMBAT_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None


class CombatCommands(commands.Cog):
    combat = app_commands.Group(
        name="combat",
        description="Manage the shared combat scene.",
    )

    def __init__(self, database: Database) -> None:
        self.database = database
        self.service = CombatService(database)
        self.world = WorldService(database)

    async def room_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        query = current.casefold().strip()
        choices: list[app_commands.Choice[str]] = []
        for area in self.world.list_areas():
            for node in self.world.area_graph(area.id).nodes:
                room = node.room
                if (
                    query
                    and query not in room.name.casefold()
                    and query not in room.id.casefold()
                ):
                    continue
                choices.append(
                    app_commands.Choice(
                        name=f"{room.name} · {area.name}"[:100],
                        value=room.id,
                    )
                )
                if len(choices) == 25:
                    return choices
        return choices

    @combat.command(name="start", description="Start combat in a room.")
    @app_commands.describe(room_id="Room where combat starts")
    @app_commands.autocomplete(room_id=room_autocomplete)
    @dm_only()
    async def start(self, interaction: discord.Interaction, room_id: str) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Combat can only be started in a server.",
                ephemeral=True,
            )
            return
        channel = await ensure_combat_channel(guild)
        if channel is None:
            await interaction.response.send_message(
                "The combat channel is unavailable.",
                ephemeral=True,
            )
            return
        try:
            scene = self.service.start(guild.id, room_id)
        except CombatError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return

        room = self.world.get_room(scene.room_id)
        room_name = room.name if room is not None else scene.room_id
        await channel.send(embed=combat_scene_embed(scene, room_name))
        await interaction.response.send_message(
            f"Combat started in {channel.mention}.",
            ephemeral=True,
        )

    @combat.command(name="status", description="Post the current combat scene.")
    @dm_only()
    async def status(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Combat status is only available in a server.",
                ephemeral=True,
            )
            return
        scene = self.service.current(guild.id)
        if scene is None:
            await interaction.response.send_message(
                "There is no active combat scene.",
                ephemeral=True,
            )
            return
        channel = await ensure_combat_channel(guild)
        if channel is None:
            await interaction.response.send_message(
                "The combat channel is unavailable.",
                ephemeral=True,
            )
            return
        room = self.world.get_room(scene.room_id)
        room_name = room.name if room is not None else scene.room_id
        await channel.send(embed=combat_scene_embed(scene, room_name))
        await interaction.response.send_message(
            f"Combat state posted in {channel.mention}.",
            ephemeral=True,
        )

    @combat.command(name="end", description="End the active combat scene.")
    @dm_only()
    async def end(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Combat can only be ended in a server.",
                ephemeral=True,
            )
            return
        try:
            scene = self.service.end(guild.id)
        except CombatError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        channel = await ensure_combat_channel(guild)
        if channel is not None:
            room = self.world.get_room(scene.room_id)
            room_name = room.name if room is not None else scene.room_id
            await channel.send(
                embed=discord.Embed(
                    title=f"Combat ended · {room_name}",
                    colour=discord.Colour.from_rgb(91, 78, 59),
                )
            )
            confirmation = f"Combat ended in {channel.mention}."
        else:
            confirmation = "Combat ended."
        await interaction.response.send_message(confirmation, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CombatCommands(bot.database))
