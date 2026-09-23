"""Interactive Discord adapter for deterministic character creation."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ...character_creation import CharacterCreationFlow, CreationStep
from ...character_creation.service import CharacterCreationService
from ...app.checks import is_dm
from . import creation as character_creation_support
from . import portrait as character_portrait_support
from . import sheet as character_sheet_support
from .presentation import (
    attribute_modifier,
    attribute_prompt,
    bonus_prompt,
    character_sheet_embed,
    creation_prompt,
    creation_prompt_for_step,
    management_prompt,
)
from .creation_views import (
    AttributeLinkSelect,
    AttributeNumberButton,
    AttributeView,
    BackButton,
    BonusButton,
    BonusView,
    ChoiceSelect,
    ChoiceView,
    ConfirmAttributesButton,
    ConfirmBonusButton,
    NameButton,
    NameModal,
    NameView,
    OwnedView,
    ResetAttributesButton,
    SkillSelect,
    SkillView,
    creation_view,
)
from .management_views import (
    ActivateCharacterButton,
    ArchiveCharacterButton,
    ArchiveConfirmationView,
    CancelArchiveButton,
    CharacterManageView,
    CharacterSelect,
    ConfirmArchiveButton,
    DMPortraitPreviewView,
    DynamicCharacterManageItem,
    PortraitPreviewView,
    RemovePortraitButton,
    UnequipCharacterButton,
)
from .sheet_views import CharacterSheetView
from ...database import Database
from ...characters.models import Character
from ...inventory import DEFAULT_ITEM_CATALOG_PATH, ItemCatalog
from ...inventory.service import InventoryService
from ...media.portraits import CharacterPortraitStore


class CharacterCommands(commands.GroupCog, group_name="character"):
    """Tracks transient flows per Discord user; only results are persisted."""

    def __init__(
        self,
        database: Database,
        portrait_store: CharacterPortraitStore | None = None,
        bot: commands.Bot | None = None,
    ) -> None:
        self.database = database
        self.bot = bot
        self.portrait_store = portrait_store or CharacterPortraitStore()
        self.service = CharacterCreationService(database)
        self.item_catalog = ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.inventory_service = InventoryService(database, self.item_catalog)
        self.sessions: dict[int, CharacterCreationFlow] = {}

    async def cog_load(self) -> None:
        if self.bot is None:
            return
        self.bot.add_dynamic_items(DynamicCharacterManageItem)
        all_characters = self.database.list_all_characters()
        characters = {
            character.character_id: character
            for character in all_characters
        }
        for state in self.database.list_character_sheet_view_states():
            character = characters.get(state.character_id)
            if character is None or state.discord_message_id is None:
                continue
            self.bot.add_view(
                self._dedicated_inventory_view(character),
                message_id=state.discord_message_id,
            )

    async def ensure_required_player_channels(self, guild) -> None:
        return await character_sheet_support.ensure_required_player_channels(
            self,
            guild,
        )

    async def active_character_changed(
        self,
        interaction: discord.Interaction,
        previous: Character | None,
        selected: Character,
    ) -> None:
        return await character_sheet_support.active_character_changed(
            self,
            interaction,
            previous,
            selected,
        )

    async def active_character_deactivated(
        self,
        interaction: discord.Interaction,
        character: Character,
    ) -> None:
        return await character_sheet_support.active_character_deactivated(
            self,
            interaction,
            character,
        )

    @staticmethod
    async def _delete_private_channel(
        interaction: discord.Interaction,
        channel_id: int,
    ) -> bool:
        return await character_sheet_support.delete_private_channel(
            interaction,
            channel_id,
        )

    @staticmethod
    async def _rename_private_channel(channel, desired_name: str) -> None:
        return await character_sheet_support.rename_private_channel(
            channel,
            desired_name,
        )

    async def _show_unplaced_character_map(
        self,
        channel,
        message_id: int | None,
        character: Character,
    ) -> None:
        return await character_sheet_support.show_unplaced_character_map(
            self,
            channel,
            message_id,
            character,
        )

    def _sheet_presentation(
        self, character: Character, *, include_inventory_summary: bool = True
    ) -> tuple[discord.Embed, discord.File | None]:
        return character_sheet_support.sheet_presentation(
            self,
            character,
            include_inventory_summary=include_inventory_summary,
        )

    def _dedicated_sheet_presentation(
        self, character: Character
    ) -> tuple[list[discord.Embed], discord.File | None]:
        return character_sheet_support.dedicated_sheet_presentation(
            self,
            character,
        )

    def _dedicated_inventory_view(self, character: Character):
        return character_sheet_support.dedicated_inventory_view(
            self,
            character,
        )

    @staticmethod
    def _sheet_channel_name(character: Character) -> str:
        return character_sheet_support.sheet_channel_name(character)

    async def _ensure_dedicated_sheet_channel(
        self,
        interaction: discord.Interaction,
        character: Character,
    ):
        return await character_sheet_support.ensure_dedicated_sheet_channel(
            self,
            interaction,
            character,
        )

    async def _ensure_dedicated_map_channel(
        self,
        interaction: discord.Interaction,
        character: Character,
    ):
        return await character_sheet_support.ensure_dedicated_map_channel(
            self,
            interaction,
            character,
        )

    async def _edit_dedicated_sheet_message(
        self,
        message: discord.Message,
        character: Character,
    ) -> None:
        return await character_sheet_support.edit_dedicated_sheet_message(
            self,
            message,
            character,
        )

    async def _refresh_dedicated_sheet(
        self,
        channel,
        character: Character,
    ) -> int:
        return await character_sheet_support.refresh_dedicated_sheet(
            self,
            channel,
            character,
        )

    async def refresh_dedicated_sheet_for(
        self,
        character: Character,
    ) -> bool:
        return await character_sheet_support.refresh_dedicated_sheet_for(
            self,
            character,
        )

    async def publish_character_sheet(
        self,
        interaction: discord.Interaction,
        user_id: int,
        character_id: int,
    ) -> None:
        return await character_sheet_support.publish_character_sheet(
            self,
            interaction,
            user_id,
            character_id,
        )

    def restore_default_portrait(
        self, user_id: int, character: Character
    ) -> Character:
        return character_portrait_support.restore_default_portrait(
            self,
            user_id,
            character,
        )

    async def _dm_portrait(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None,
        remove: bool,
    ) -> None:
        return await character_portrait_support.dm_portrait(
            self,
            interaction,
            image,
            remove,
        )

    @app_commands.command(name="create", description="Start creating your character.")
    async def create(self, interaction: discord.Interaction) -> None:
        return await character_creation_support.create(
            self,
            interaction,
        )

    @app_commands.command(
        name="sheet", description="Open your active character sheet privately."
    )
    async def sheet(self, interaction: discord.Interaction) -> None:
        return await character_sheet_support.show_sheet(
            self,
            interaction,
        )

    @app_commands.command(
        name="manage", description="Choose or archive one of your characters."
    )
    async def manage(self, interaction: discord.Interaction) -> None:
        characters = self.database.list_characters(interaction.user.id)
        if not characters:
            await interaction.response.send_message(
                "You have no selectable characters. Use `/character create`.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            management_prompt(characters),
            view=CharacterManageView(self, interaction.user.id, characters),
            ephemeral=True,
        )

    @app_commands.command(
        name="portrait", description="View, upload, or remove your active portrait."
    )
    @app_commands.describe(
        image="Optional PNG, JPEG, or WebP image (maximum 5 MB)",
        remove="Remove the current portrait",
    )
    async def portrait(
        self,
        interaction: discord.Interaction,
        image: discord.Attachment | None = None,
        remove: bool = False,
    ) -> None:
        return await character_portrait_support.portrait(
            self,
            interaction,
            image,
            remove,
            is_dm_check=is_dm,
        )

    @app_commands.command(
        name="removeportrait", description="Remove your active character's portrait."
    )
    async def remove_portrait(self, interaction: discord.Interaction) -> None:
        return await character_portrait_support.remove_portrait(
            self,
            interaction,
            is_dm_check=is_dm,
        )

    async def submit_component(
        self, interaction: discord.Interaction, user_id: int, value: object
    ) -> None:
        return await character_creation_support.submit_component(
            self,
            interaction,
            user_id,
            value,
        )

    async def back_component(
        self, interaction: discord.Interaction, user_id: int
    ) -> None:
        return await character_creation_support.back_component(
            self,
            interaction,
            user_id,
        )

    @app_commands.command(name="cancel", description="Cancel character creation.")
    async def cancel(self, interaction: discord.Interaction) -> None:
        return await character_creation_support.cancel(
            self,
            interaction,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(
        CharacterCommands(
            bot.database,
            CharacterPortraitStore(
                getattr(
                    getattr(bot, "config", None),
                    "character_media_path",
                    "data/characters",
                )
            ),
            bot,
        )
    )
