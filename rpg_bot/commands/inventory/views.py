"""Discord UI for browsing and acting on character inventory."""

from __future__ import annotations

import discord

from ...inventory import InventoryState, ItemType
from ...inventory.service import InventoryError, InventoryService
from ...characters.models import Character
from ...world.service import WorldService
from .presentation import (
    _item_label_for_quantity,
    _stacked_inventory_items,
    readable_field_pages,
)


async def _show_inventory(*args, **kwargs) -> None:
    from .cog import show_inventory

    await show_inventory(*args, **kwargs)


async def _refresh_character_sheet(
    interaction: discord.Interaction,
    character: Character,
) -> None:
    from .cog import refresh_character_sheet

    await refresh_character_sheet(interaction, character)


async def _announce_room_action_runtime(
    interaction: discord.Interaction,
    character: Character,
    description: str,
) -> None:
    from .cog import _announce_room_action

    await _announce_room_action(interaction, character, description)


def _forget_open_inventory(user_id: int, character_id: int | None = None) -> None:
    from .cog import forget_open_inventory

    forget_open_inventory(user_id, character_id)


class InventoryOwnedView(discord.ui.View):
    def __init__(
        self,
        service: InventoryService,
        user_id: int,
        character_id: int,
        *,
        persistent: bool = False,
    ) -> None:
        super().__init__(timeout=None if persistent else 15 * 60)
        self.service = service
        self.user_id = user_id
        self.character_id = character_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This inventory belongs to another player.", ephemeral=True
        )
        return False

    def character(self) -> Character:
        character = self.service.database.get_character_by_id(
            self.user_id, self.character_id
        )
        if character is None:
            raise InventoryError("That character is no longer available.")
        return character


class InventoryItemSelect(discord.ui.Select):
    def __init__(self, owner_view: InventoryView, inventory: InventoryState) -> None:
        self.owner_view = owner_view
        start = owner_view.page * 25
        stacked_items = _stacked_inventory_items(
            inventory.items, owner_view.service.catalog
        )
        options = [
            discord.SelectOption(
                label=_item_label_for_quantity(
                    item, quantity, owner_view.service.catalog
                )[:100],
                value=item.instance_id,
                description=owner_view.service.catalog.get(item.template_id).rarity[:100],
                default=item.instance_id == owner_view.selected_id,
            )
            for item, quantity in stacked_items[start : start + 25]
        ]
        super().__init__(
            placeholder="Select an item",
            options=options or [
                discord.SelectOption(label="Inventory is empty", value="empty")
            ],
            disabled=not options,
            row=0,
            custom_id="inventory:item",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == "empty":
            return
        character = self.owner_view.character()
        selected_id = self.values[0]
        selected = self.owner_view.service.database.get_character_inventory(
            self.owner_view.character_id
        ).item(selected_id)
        template = self.owner_view.service.catalog.get(selected.template_id)
        reading_id = (
            selected_id
            if self.owner_view.reading_id is not None
            and template.item_type is ItemType.READABLE
            else None
        )
        await _show_inventory(
            interaction,
            self.owner_view.service,
            character,
            selected_id=selected_id,
            page=self.owner_view.page,
            reading_id=reading_id,
            reading_page=0,
            edit=True,
            dedicated_cog=self.owner_view.dedicated_cog,
        )


class InventoryView(InventoryOwnedView):
    def __init__(
        self,
        service: InventoryService,
        user_id: int,
        character_id: int,
        inventory: InventoryState,
        selected_id: str | None = None,
        page: int = 0,
        reading_id: str | None = None,
        reading_page: int = 0,
        dedicated_cog=None,
    ) -> None:
        super().__init__(
            service,
            user_id,
            character_id,
            persistent=dedicated_cog is not None,
        )
        self.dedicated_cog = dedicated_cog
        self.selected_id = selected_id
        self.page = page
        self.reading_id = reading_id
        self.reading_page = reading_page
        stacked_items = _stacked_inventory_items(inventory.items, service.catalog)
        self.page_count = max(1, (len(stacked_items) + 24) // 25)
        self.add_item(InventoryItemSelect(self, inventory))
        if page <= 0:
            self.remove_item(self.previous_page)
        if page >= self.page_count - 1:
            self.remove_item(self.next_page)
        selected = inventory.item(selected_id) if selected_id is not None else None
        template = (
            service.catalog.get(selected.template_id) if selected is not None else None
        )
        is_equipped = selected_id in inventory.equipment.values()
        can_equip = template is not None and (
            template.item_type
            in {ItemType.WEAPON, ItemType.ARMOR, ItemType.CLOTHING}
            or (
                template.item_type is ItemType.CONTAINER
                and template.can_equip
            )
        )
        if not can_equip or is_equipped:
            self.remove_item(self.equip_button)
        if not is_equipped:
            self.remove_item(self.unequip_button)
        if template is None or template.item_type is not ItemType.CONSUMABLE:
            self.remove_item(self.use_button)
        if template is None or template.item_type is not ItemType.READABLE:
            self.remove_item(self.read_button)
        if selected is None or is_equipped:
            self.remove_item(self.drop_button)
        if reading_id is None:
            self.remove_item(self.reading_previous_button)
            self.remove_item(self.reading_next_button)
        else:
            self.read_button.label = "Close reading"
            self.read_button.style = discord.ButtonStyle.secondary
            reading_template = service.read(self.character(), reading_id)
            reading_pages = readable_field_pages(reading_template)
            self.reading_page = min(max(0, reading_page), len(reading_pages) - 1)
            if self.reading_page == 0:
                self.remove_item(self.reading_previous_button)
            if self.reading_page >= len(reading_pages) - 1:
                self.remove_item(self.reading_next_button)
        if self.dedicated_cog is not None:
            self.back_button.label = "Refresh"
            self.back_button.emoji = "🔄"
            self.back_button.custom_id = "character-sheet:refresh"

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        if self.selected_id is None:
            await interaction.response.send_message(
                "Select an item first.", ephemeral=True
            )
            return
        character = self.character()
        equipment_message = None
        try:
            inventory_before = self.service.database.get_character_inventory(
                self.character_id
            )
            selected_item = inventory_before.item(self.selected_id)
            selected_template = self.service.catalog.get(selected_item.template_id)
            if action == "equip":
                slot = self.service.equip(character, self.selected_id)
                equipment_message = (
                    f"**{character.name}** equips **{selected_template.name}** "
                    f"as **{slot.value.replace('_', ' ').title()}**."
                )
            elif action == "unequip":
                self.service.unequip(character, self.selected_id)
                equipment_message = (
                    f"**{character.name}** unequips **{selected_template.name}**."
                )
            elif action == "use":
                character = self.service.use(character, self.selected_id)
        except (InventoryError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        inventory = self.service.database.get_character_inventory(self.character_id)
        selected = (
            self.selected_id
            if any(item.instance_id == self.selected_id for item in inventory.items)
            else None
        )
        await _show_inventory(
            interaction,
            self.service,
            character,
            selected_id=selected,
            page=self.page,
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )
        if self.dedicated_cog is None:
            await _refresh_character_sheet(interaction, character)
        if equipment_message is not None:
            await _announce_room_action_runtime(
                interaction, character, equipment_message
            )

    @discord.ui.button(
        label="Equip",
        style=discord.ButtonStyle.success,
        row=1,
        custom_id="inventory:equip",
    )
    async def equip_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self._run(interaction, "equip")

    @discord.ui.button(
        label="Unequip",
        style=discord.ButtonStyle.secondary,
        row=1,
        custom_id="inventory:unequip",
    )
    async def unequip_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self._run(interaction, "unequip")

    @discord.ui.button(
        label="Use",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="inventory:use",
    )
    async def use_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self._run(interaction, "use")

    @discord.ui.button(
        label="Read",
        style=discord.ButtonStyle.primary,
        row=1,
        custom_id="inventory:read",
    )
    async def read_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if self.reading_id is not None:
            character = self.character()
            try:
                template = self.service.read(character, self.reading_id)
            except (InventoryError, ValueError) as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            await _show_inventory(
                interaction,
                self.service,
                character,
                selected_id=self.selected_id,
                page=self.page,
                edit=True,
                dedicated_cog=self.dedicated_cog,
            )
            await _announce_room_action_runtime(
                interaction,
                character,
                f"**{character.name}** stops reading and puts "
                f"**{template.name}** away.",
            )
            return
        if self.selected_id is None:
            await interaction.response.send_message(
                "Select a readable item first.", ephemeral=True
            )
            return
        character = self.character()
        try:
            template = self.service.read(character, self.selected_id)
        except (InventoryError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await _show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.selected_id,
            reading_page=0,
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )
        await _announce_room_action_runtime(
            interaction,
            character,
            f"**{character.name}** takes out **{template.name}** and starts reading.",
        )

    @discord.ui.button(
        label="Drop",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="inventory:drop",
    )
    async def drop_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if self.selected_id is None:
            await interaction.response.send_message(
                "Select an item first.", ephemeral=True
            )
            return
        character = self.character()
        try:
            moved = WorldService(
                self.service.database, self.service.catalog
            ).drop_item(self.character_id, self.selected_id)
        except ValueError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        inventory = self.service.database.get_character_inventory(self.character_id)
        selected = (
            self.selected_id
            if any(item.instance_id == self.selected_id for item in inventory.items)
            else None
        )
        stacked_items = _stacked_inventory_items(
            inventory.items, self.service.catalog
        )
        await _show_inventory(
            interaction,
            self.service,
            character,
            selected_id=selected,
            page=min(self.page, max(0, (len(stacked_items) - 1) // 25)),
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )
        if self.dedicated_cog is None:
            await _refresh_character_sheet(interaction, character)
        await interaction.followup.send(
            f"**{character.name}** dropped {moved.quantity} × {moved.item.name}."
        )

    @discord.ui.button(
        label="Back to sheet",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="inventory:back",
    )
    async def back_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        if self.dedicated_cog is not None:
            await _show_inventory(
                interaction,
                self.service,
                self.character(),
                selected_id=self.selected_id,
                page=self.page,
                edit=True,
                dedicated_cog=self.dedicated_cog,
            )
            return
        from ..character import CharacterSheetView

        character = self.character()
        character_cog = interaction.client.get_cog("CharacterCommands")
        if character_cog is None:
            await interaction.response.send_message(
                "The character sheet is temporarily unavailable.", ephemeral=True
            )
            return
        embed, portrait_file = character_cog._sheet_presentation(character)
        try:
            await interaction.response.edit_message(
                embed=embed,
                attachments=[portrait_file] if portrait_file is not None else [],
                view=CharacterSheetView(
                    character_cog,
                    self.user_id,
                    self.character_id,
                ),
            )
        finally:
            if portrait_file is not None:
                portrait_file.close()
        _forget_open_inventory(self.user_id, self.character_id)

    @discord.ui.button(
        label="Previous items",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="inventory:previous-items",
    )
    async def previous_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await _show_inventory(
            interaction,
            self.service,
            self.character(),
            page=max(0, self.page - 1),
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )

    @discord.ui.button(
        label="Next items",
        style=discord.ButtonStyle.secondary,
        row=2,
        custom_id="inventory:next-items",
    )
    async def next_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await _show_inventory(
            interaction,
            self.service,
            self.character(),
            page=min(self.page_count - 1, self.page + 1),
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )

    @discord.ui.button(
        label="Previous page",
        style=discord.ButtonStyle.secondary,
        row=3,
        custom_id="inventory:previous-page",
    )
    async def reading_previous_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await _show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.reading_id,
            reading_page=max(0, self.reading_page - 1),
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )

    @discord.ui.button(
        label="Next page",
        style=discord.ButtonStyle.secondary,
        row=3,
        custom_id="inventory:next-page",
    )
    async def reading_next_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await _show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.reading_id,
            reading_page=self.reading_page + 1,
            edit=True,
            dedicated_cog=self.dedicated_cog,
        )
