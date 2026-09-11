"""Discord RPG bot entry point."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .checks import DMRoleRequired
from .config import Config
from .database import Database


LOGGER = logging.getLogger(__name__)


REQUIRED_BOT_PERMISSIONS = discord.Permissions(
    manage_channels=True,
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    connect=True,
    speak=True,
)


class RPGBot(commands.Bot):
    def __init__(self, config: Config, database: Database) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config = config
        self.database = database

    async def setup_hook(self) -> None:
        await self.load_extension("rpg_bot.commands.player")
        await self.load_extension("rpg_bot.commands.dm")
        await self.load_extension("rpg_bot.commands.character")
        await self.load_extension("rpg_bot.commands.inventory")
        await self.load_extension("rpg_bot.commands.world")

        if self.config.discord_guild_id is not None:
            guild = discord.Object(id=self.config.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            LOGGER.info("Synchronized %d command(s) to development guild %s", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            LOGGER.info("Synchronized %d global command(s)", len(synced))

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Logged in as %s (ID: %s)", self.user, self.user.id)
            for guild in self.guilds:
                member = guild.me
                if member is None:
                    continue
                missing = [
                    name.replace("_", " ").title()
                    for name, required in REQUIRED_BOT_PERMISSIONS
                    if required and not getattr(member.guild_permissions, name)
                ]
                if missing:
                    install_url = discord.utils.oauth_url(
                        self.user.id,
                        permissions=REQUIRED_BOT_PERMISSIONS,
                        scopes=("bot", "applications.commands"),
                    )
                    LOGGER.warning(
                        "Bot is missing permissions in %s: %s. Reauthorize with: %s",
                        guild.name,
                        ", ".join(missing),
                        install_url,
                    )


def configure_error_handling(bot: RPGBot) -> None:
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, DMRoleRequired):
            message = str(error)
        else:
            LOGGER.error(
                "Unhandled slash command error in /%s",
                interaction.command.name if interaction.command else "unknown",
                exc_info=(type(error), error, error.__traceback__),
            )
            message = "Something went wrong while running that command. Check the bot console."

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_env()
        database = Database(config.database_path)
        database.initialize()
        bot = RPGBot(config, database)
        configure_error_handling(bot)
        bot.run(config.discord_token, log_handler=None)
    except ValueError as error:
        LOGGER.error("Configuration error: %s", error)


if __name__ == "__main__":
    main()
