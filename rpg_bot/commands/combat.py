"""Discord adapter for the shared landmark-based combat scene."""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..app.checks import dm_only
from ..combat import CombatScene
from ..combat.service import CombatError, CombatService
from ..database import Database
from ..discord_support.combat_messages import CombatMessageStore
from ..discord_support.combat_publisher import (
    CombatPublisher, combat_scene_embed, ensure_combat_channel,
)
from .combat_views import CombatActionView
from ..world.service import WorldService


LOGGER = logging.getLogger(__name__)


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
        self.message_store = CombatMessageStore(self.database.path)
        self.publisher = CombatPublisher(
            self.service, self.world, self.message_store, self.database.path,
            lambda scene_id: CombatOpenView(self, scene_id),
        )
        self._last_scenes = self.publisher.last_scenes
        self._scene_messages = self.publisher.messages
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
        return await self.publisher.publish(guild, scene, channel=channel)

    async def _publish_ended(
        self, guild: discord.Guild, previous: CombatScene,
    ) -> None:
        await self.publisher.end(guild, previous)

    @tasks.loop(seconds=2.0)
    async def sync_dashboard_combat(self) -> None:
        for guild in self.bot.guilds:
            try:
                scene = self.service.current(guild.id)
                previous = self._last_scenes.get(guild.id)
                if scene is None:
                    if previous is not None:
                        await self._publish_ended(guild, previous)
                    else:
                        # The encounter may have ended in Dashboard while
                        # Discord was offline. Finalize the last map from the
                        # persisted scene and leave the history intact.
                        saved = self.message_store.get(guild.id)
                        if saved is not None:
                            finished = self.service.repository.get_scene(
                                saved.scene_id,
                            )
                            if finished is not None and finished.status.value == "ended":
                                await self._publish_ended(guild, finished)
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
