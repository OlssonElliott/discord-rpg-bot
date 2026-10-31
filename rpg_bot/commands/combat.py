"""Discord adapter for the shared landmark-based combat scene."""

import asyncio
from hashlib import sha256
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..app.checks import dm_only
from ..combat import CombatScene
from ..combat.service import CombatError, CombatService
from ..database import Database
from ..discord_support.combat_messages import CombatMessageStore
from ..map_renderer.combat import render_combat_map
from .combat_views import CombatActionView
from ..world.service import WorldService


COMBAT_CHANNEL_NAME = "combat"
LOGGER = logging.getLogger(__name__)


def _field_text(lines: list[str], empty: str) -> str:
    text = "\n".join(lines) or empty
    return text if len(text) <= 1024 else f"{text[:1021]}..."


def combat_scene_embed(
    scene: CombatScene,
    room_name: str,
    image_filename: str = "combat-map.png",
) -> discord.Embed:
    """Compact player-facing status; the attachment shows the location graph."""
    embed = discord.Embed(
        title=f"Combat · {room_name}",
        description="Choose **Actions** on your turn to move or fight.",
        colour=discord.Colour.from_rgb(111, 37, 32),
    )
    active = scene.current_combatant()
    if active is not None:
        embed.description = f"**Round {scene.round_number}** · {active.name}'s turn. Use **Actions** to play."
    order = [
        (
            f"{'▶ ' if active is not None and actor.kind == active.kind and actor.source_id == active.source_id else ''}"
            f"{actor.name} · Initiative {actor.initiative_score}"
        )
        for actor in scene.initiative_order()
    ]
    embed.add_field(
        name="Turn order",
        value=_field_text(order, "No combatants"),
        inline=False,
    )
    embed.set_image(url=f"attachment://{image_filename}")
    embed.set_footer(text=f"Scene #{scene.id}")
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

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.database: Database = bot.database
        self.service = CombatService(self.database)
        self.world = WorldService(self.database)
        self._scene_messages: dict[int, discord.Message] = {}
        self.message_store = CombatMessageStore(self.database.path)
        self._last_scenes: dict[int, CombatScene] = {}
        self.sync_dashboard_combat.start()

    def cog_unload(self) -> None:
        self.sync_dashboard_combat.cancel()

    async def _publish_scene(
        self,
        guild: discord.Guild,
        scene: CombatScene,
        *,
        channel: discord.TextChannel | None = None,
    ) -> discord.TextChannel | None:
        channel = channel or await ensure_combat_channel(guild)
        if channel is None:
            return None
        room = self.world.get_room(scene.room_id)
        room_name = room.name if room is not None else scene.room_id
        try:
            image = await asyncio.to_thread(render_combat_map, scene, room_name)
        except Exception:
            LOGGER.exception(
                "Combat map rendering failed for guild %s, scene %s",
                guild.id, scene.id,
            )
            return None
        # Use a content-specific attachment name. Reusing the same filename
        # when editing an attachment-backed embed can leave a stale image in
        # the Discord client's cache.
        image_filename = (
            f"combat-map-{sha256(image.getvalue()).hexdigest()[:12]}.png"
        )
        embed = combat_scene_embed(scene, room_name, image_filename)

        message = self._scene_messages.get(guild.id)
        saved = self.message_store.get(guild.id)
        if saved is not None and saved.scene_id != scene.id:
            # Never edit a previous encounter's card with the new scene.
            message = None
            self._scene_messages.pop(guild.id, None)
        if message is None and saved is not None and saved.scene_id == scene.id:
            try:
                saved_channel = guild.get_channel(saved.channel_id)
                if saved_channel is not None:
                    message = await saved_channel.fetch_message(saved.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
        if message is not None:
            try:
                # Replace the attachment in place: Discord keeps one card
                # while movement and dashboard changes regenerate the image.
                image.seek(0)
                edited = await message.edit(
                    embed=embed,
                    view=CombatOpenView(self, scene.id),
                    attachments=[discord.File(image, filename=image_filename)],
                )
                self._scene_messages[guild.id] = edited
                self.message_store.save(
                    guild.id, scene.id, edited.channel.id, edited.id,
                )
                self._last_scenes[guild.id] = scene
                return channel
            except discord.NotFound:
                self._scene_messages.pop(guild.id, None)
            except discord.HTTPException:
                LOGGER.exception(
                    "Combat map upload/edit failed in guild %s, scene %s",
                    guild.id, scene.id,
                )
                return None
        try:
            image.seek(0)
            self._scene_messages[guild.id] = await channel.send(
                embed=embed,
                view=CombatOpenView(self, scene.id),
                file=discord.File(image, filename=image_filename),
            )
            sent = self._scene_messages[guild.id]
            self.message_store.save(guild.id, scene.id, channel.id, sent.id)
            self._last_scenes[guild.id] = scene
        except discord.HTTPException:
            LOGGER.exception(
                "Combat map upload/send failed in guild %s, scene %s",
                guild.id, scene.id,
            )
            return None
        return channel

    async def _publish_ended(
        self,
        guild: discord.Guild,
        previous: CombatScene,
    ) -> None:
        room = self.world.get_room(previous.room_id)
        room_name = room.name if room is not None else previous.room_id
        embed = discord.Embed(
            title=f"Combat ended · {room_name}",
            colour=discord.Colour.from_rgb(91, 78, 59),
        )
        message = self._scene_messages.pop(guild.id, None)
        saved = self.message_store.get(guild.id)
        if message is None and saved is not None:
            try:
                old_channel = guild.get_channel(saved.channel_id)
                if old_channel is not None:
                    message = await old_channel.fetch_message(saved.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
        self.message_store.clear(guild.id)
        if message is not None:
            try:
                await message.edit(embed=embed, view=None, attachments=[])
            except discord.HTTPException:
                LOGGER.exception(
                    "Could not close combat scene message in guild %s",
                    guild.id,
                )
        else:
            channel = await ensure_combat_channel(guild)
            if channel is not None:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    LOGGER.exception(
                        "Could not publish ended combat in guild %s",
                        guild.id,
                    )
        self._last_scenes.pop(guild.id, None)

    @tasks.loop(seconds=2.0)
    async def sync_dashboard_combat(self) -> None:
        for guild in self.bot.guilds:
            try:
                scene = self.service.current(guild.id)
                previous = self._last_scenes.get(guild.id)
                if scene is None:
                    if previous is not None:
                        await self._publish_ended(guild, previous)
                    continue
                if previous != scene or guild.id not in self._scene_messages:
                    await self._publish_scene(guild, scene)
            except Exception:
                # A failed Discord upload must not kill the sync task for all
                # guilds. Keep retrying and surface the actual traceback.
                LOGGER.exception(
                    "Combat synchronization failed in guild %s",
                    guild.id,
                )

    @sync_dashboard_combat.before_loop
    async def before_sync_dashboard_combat(self) -> None:
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            saved = self.message_store.get(guild.id)
            scene = self.service.current(guild.id)
            if saved is not None and scene is not None and saved.scene_id == scene.id:
                self.bot.add_view(CombatOpenView(self, scene.id), message_id=saved.message_id)

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

        published = await self._publish_scene(guild, scene, channel=channel)
        await interaction.response.send_message(
            (
                f"Combat started in {channel.mention}."
                if published is not None
                else "Combat started, but the map could not be published. "
                     "Check the bot console for the error."
            ),
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
        published = await self._publish_scene(guild, scene, channel=channel)
        await interaction.response.send_message(
            (
                f"Combat map refreshed in {channel.mention}."
                if published is not None
                else "The combat map could not be refreshed. "
                     "Check the bot console for the error."
            ),
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
        await self._publish_ended(guild, scene)
        if channel is not None:
            confirmation = f"Combat ended in {channel.mention}."
        else:
            confirmation = "Combat ended."
        await interaction.response.send_message(confirmation, ephemeral=True)


class CombatOpenView(discord.ui.View):
    """Public button opening an owner-validated ephemeral turn menu."""

    def __init__(self, cog: CombatCommands, scene_id: int) -> None:
        super().__init__(timeout=None)
        self.cog = cog
        self.scene_id = scene_id

    @discord.ui.button(label="Actions", style=discord.ButtonStyle.primary, custom_id="rpg:combat:actions")
    async def actions(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        scene = self.cog.service.current(interaction.guild_id)
        if scene is None or scene.id != self.scene_id:
            await interaction.response.send_message("That encounter has ended.", ephemeral=True)
            return
        actor = scene.current_combatant()
        if actor is None or actor.kind.value != "character":
            await interaction.response.send_message("It is not a player character's turn.", ephemeral=True)
            return
        character = self.cog.database.get_character(interaction.user.id)
        if character is None or str(character.character_id) != actor.source_id:
            await interaction.response.send_message("It is not your character's turn.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"Round {scene.round_number} · {actor.name}'s turn",
            view=CombatActionView(self.cog, scene.id, actor.source_id),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CombatCommands(bot))
