"""Discord UI for character management and portrait actions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord

from ...database import CharacterNotFoundError
from ...characters.models import Character
from ...media.portraits import is_default_portrait_key
from .creation_views import OwnedView
from .presentation import management_prompt

if TYPE_CHECKING:
    from .cog import CharacterCommands


class CharacterSelect(discord.ui.Select):
    def __init__(
        self,
        manage_view: CharacterManageView,
        characters: list[Character],
    ) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("select"),
            placeholder="Choose a character",
            options=[
                discord.SelectOption(
                    label=character.name,
                    value=str(character.character_id),
                    description="Currently active" if character.is_active else None,
                    default=character.character_id == manage_view.selected_id,
                )
                for character in characters[:25]
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = int(self.values[0])
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            selected_id,
        )
        await interaction.response.edit_message(
            content=management_prompt(characters, selected_id), view=view
        )


class ActivateCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        selected = next(
            (
                character
                for character in manage_view.characters
                if character.character_id == manage_view.selected_id
            ),
            None,
        )
        super().__init__(
            custom_id=manage_view.component_id("activate"),
            label="Use character",
            style=discord.ButtonStyle.primary,
            disabled=selected is None or selected.is_active,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = self.manage_view.selected_id
        if selected_id is None:
            return
        await interaction.response.defer()
        try:
            previous = self.manage_view.cog.database.get_character(
                self.manage_view.user_id
            )
            selected = self.manage_view.cog.database.select_character(
                self.manage_view.user_id, selected_id
            )
        except CharacterNotFoundError as error:
            await interaction.edit_original_response(content=str(error), view=None)
            return
        await self.manage_view.cog.active_character_changed(
            interaction, previous, selected
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            selected_id,
        )
        await interaction.edit_original_response(
            content=management_prompt(characters, selected_id), view=view
        )


class UnequipCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("unequip"),
            label="Unequip active",
            style=discord.ButtonStyle.secondary,
            disabled=not any(
                character.is_active for character in manage_view.characters
            ),
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        active = next(
            (
                character
                for character in self.manage_view.characters
                if character.is_active
            ),
            None,
        )
        self.manage_view.cog.database.deactivate_character(
            self.manage_view.user_id
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            self.manage_view.selected_id,
        )
        await interaction.response.edit_message(
            content=(
                "No character is currently active.\n"
                f"{management_prompt(characters, self.manage_view.selected_id)}"
            ),
            view=view,
        )
        if active is not None:
            await self.manage_view.cog.active_character_deactivated(
                interaction, active
            )


class ArchiveCharacterButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(
            custom_id=manage_view.component_id("archive"),
            label="Remove from Discord",
            style=discord.ButtonStyle.danger,
            disabled=manage_view.selected_id is None,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_id = self.manage_view.selected_id
        if selected_id is None:
            return
        selected = next(
            character
            for character in self.manage_view.characters
            if character.character_id == selected_id
        )
        await interaction.response.edit_message(
            content=(
                f"Remove **{selected.name}** from your selectable characters?\n"
                "Its database record will be kept."
            ),
            view=ArchiveConfirmationView(self.manage_view, selected),
        )


class RemovePortraitButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        selected = next(
            (
                character
                for character in manage_view.characters
                if character.character_id == manage_view.selected_id
            ),
            None,
        )
        super().__init__(
            custom_id=manage_view.component_id("remove-portrait"),
            label="Remove portrait",
            style=discord.ButtonStyle.secondary,
            disabled=(
                selected is None
                or not getattr(selected, "portrait_key", None)
                or is_default_portrait_key(getattr(selected, "portrait_key", None))
            ),
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = next(
            (
                character
                for character in self.manage_view.characters
                if character.character_id == self.manage_view.selected_id
            ),
            None,
        )
        if selected is None or not selected.portrait_key:
            return
        updated = self.manage_view.cog.restore_default_portrait(
            self.manage_view.user_id, selected
        )
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            updated.character_id,
        )
        await interaction.response.edit_message(
            content=(
                f"Restored **{updated.name}**'s default portrait.\n"
                f"{management_prompt(characters, updated.character_id)}"
            ),
            view=view,
        )


class PortraitPreviewView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        character_id: int,
        character_name: str,
        portrait_key: str,
    ) -> None:
        super().__init__(cog, user_id)
        self.character_id = character_id
        self.character_name = character_name
        self.portrait_key = portrait_key
        if is_default_portrait_key(portrait_key):
            self.remove.disabled = True
            self.remove.label = "Using default portrait"

    @discord.ui.button(
        label="Remove portrait",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def remove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        try:
            character = self.cog.database.get_character_by_id(
                self.user_id, self.character_id
            )
            if character is None:
                raise CharacterNotFoundError("That character is not selectable.")
            self.cog.restore_default_portrait(self.user_id, character)
        except CharacterNotFoundError as error:
            await interaction.response.edit_message(
                content=str(error), embed=None, attachments=[], view=None
            )
            return
        self.cog.portrait_store.remove(self.portrait_key)
        await interaction.response.edit_message(
            content=f"Restored **{self.character_name}**'s default portrait.",
            embed=None,
            attachments=[],
            view=None,
        )


class DMPortraitPreviewView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        portrait_key: str | None,
    ) -> None:
        super().__init__(cog, user_id)
        self.portrait_key = portrait_key
        if portrait_key is None:
            self.remove.disabled = True
            self.remove.label = "Using default portrait"

    @discord.ui.button(
        label="Remove portrait",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
    )
    async def remove(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        del button
        self.cog.database.set_dm_portrait(self.user_id, None)
        self.cog.portrait_store.remove(self.portrait_key)
        await interaction.response.edit_message(
            content="Restored your default Dungeon Master portrait.",
            embed=None,
            attachments=[],
            view=None,
        )


class ConfirmArchiveButton(discord.ui.Button):
    def __init__(
        self, manage_view: CharacterManageView, character: Character
    ) -> None:
        self.manage_view = manage_view
        self.character = character
        super().__init__(label="Confirm removal", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            archived = self.manage_view.cog.database.archive_character(
                self.manage_view.user_id, self.character.character_id
            )
        except CharacterNotFoundError as error:
            await interaction.response.edit_message(content=str(error), view=None)
            return
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        if not characters:
            await interaction.response.edit_message(
                content=(
                    f"Archived **{archived.name}**. "
                    "You have no selectable characters."
                ),
                view=None,
            )
            if self.character.is_active:
                await self.manage_view.cog.active_character_deactivated(
                    interaction, self.character
                )
            return
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
        )
        await interaction.response.edit_message(
            content=(
                f"Archived **{archived.name}**.\n"
                f"{management_prompt(characters)}"
            ),
            view=view,
        )
        if self.character.is_active:
            replacement = self.manage_view.cog.database.get_character(
                self.manage_view.user_id
            )
            if replacement is not None:
                await self.manage_view.cog.active_character_changed(
                    interaction, self.character, replacement
                )


class CancelArchiveButton(discord.ui.Button):
    def __init__(self, manage_view: CharacterManageView) -> None:
        self.manage_view = manage_view
        super().__init__(label="Cancel", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        characters = self.manage_view.cog.database.list_characters(
            self.manage_view.user_id
        )
        view = CharacterManageView(
            self.manage_view.cog,
            self.manage_view.user_id,
            characters,
            self.manage_view.selected_id,
        )
        await interaction.response.edit_message(
            content=management_prompt(
                characters,
                self.manage_view.selected_id,
            ),
            view=view,
        )


class ArchiveConfirmationView(OwnedView):
    def __init__(
        self, manage_view: CharacterManageView, character: Character
    ) -> None:
        super().__init__(manage_view.cog, manage_view.user_id)
        self.add_item(ConfirmArchiveButton(manage_view, character))
        self.add_item(CancelArchiveButton(manage_view))


class CharacterManageView(OwnedView):
    def __init__(
        self,
        cog: CharacterCommands,
        user_id: int,
        characters: list[Character],
        selected_id: int | None = None,
    ) -> None:
        super().__init__(cog, user_id, timeout=None)
        self.characters = characters
        self.selected_id = selected_id
        self.add_item(
            DynamicCharacterManageItem(CharacterSelect(self, characters))
        )
        self.add_item(
            DynamicCharacterManageItem(ActivateCharacterButton(self))
        )
        self.add_item(
            DynamicCharacterManageItem(UnequipCharacterButton(self))
        )
        self.add_item(
            DynamicCharacterManageItem(ArchiveCharacterButton(self))
        )
        self.add_item(
            DynamicCharacterManageItem(RemovePortraitButton(self))
        )

    def component_id(self, action: str) -> str:
        selected = self.selected_id if self.selected_id is not None else "none"
        return f"character-manage:{action}:{self.user_id}:{selected}"


class DynamicCharacterManageItem(
    discord.ui.DynamicItem[discord.ui.Item],
    template=(
        r"character-manage:(?P<action>select|activate|unequip|archive|remove-portrait):"
        r"(?P<user_id>\d+):(?P<selected_id>none|\d+)"
    ),
):
    """Rebuild a manage callback from its ID after a process restart."""

    def __init__(
        self,
        item: discord.ui.Item,
        user_id: int | None = None,
    ) -> None:
        super().__init__(item)
        if user_id is None:
            match = self.template.fullmatch(self.custom_id)
            if match is None:
                raise ValueError(
                    "Invalid character management component ID."
                )
            user_id = int(match.group("user_id"))
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Item,
        match: re.Match[str],
    ) -> DynamicCharacterManageItem:
        from .cog import CharacterCommands

        cog = interaction.client.get_cog("CharacterCommands")
        if not isinstance(cog, CharacterCommands):
            raise RuntimeError("Character commands are not loaded.")
        user_id = int(match.group("user_id"))
        selected_value = match.group("selected_id")
        selected_id = (
            None if selected_value == "none" else int(selected_value)
        )
        characters = cog.database.list_characters(user_id)
        manage_view = CharacterManageView(
            cog,
            user_id,
            characters,
            selected_id,
        )
        rebuilt = next(
            child.item
            for child in manage_view.children
            if isinstance(child, DynamicCharacterManageItem)
            and child.custom_id == item.custom_id
        )
        return cls(rebuilt, user_id)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This character management panel belongs to another player.",
            ephemeral=True,
        )
        return False
