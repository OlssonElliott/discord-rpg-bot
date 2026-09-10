"""Private Discord inventory browser and item actions."""

from __future__ import annotations

from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from ..inventory import (
    DEFAULT_ITEM_CATALOG_PATH,
    EquipmentSlot,
    InventoryState,
    ItemCatalog,
    ItemInstance,
    ItemTemplate,
    ItemType,
)
from ..inventory_service import InventoryError, InventoryService
from ..models import Character


DISCORD_FIELD_LIMIT = 1024
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
READING_SEPARATOR = "──────────"


def _item_label(item: ItemInstance, catalog: ItemCatalog) -> str:
    template = catalog.get(item.template_id)
    quantity = f" ×{item.quantity}" if item.quantity > 1 else ""
    return f"{template.name}{quantity}"


def _inventory_lines(
    inventory: InventoryState,
    catalog: ItemCatalog,
) -> list[str]:
    equipped_ids = set(inventory.equipment.values())
    lines: list[str] = []
    for item in inventory.items:
        if item.instance_id in equipped_ids:
            continue
        template = catalog.get(item.template_id)
        weight = template.weight * item.quantity
        capacity_bonus = (
            f" • +{template.capacity or 0} storage when equipped"
            if template.item_type is ItemType.CONTAINER
            else ""
        )
        lines.append(f"• {_item_label(item, catalog)} • {weight} weight{capacity_bonus}")
    return lines


def _fit_field(lines: list[str], limit: int = 1024) -> str:
    visible: list[str] = []
    length = 0
    for line in lines:
        added = len(line) + (1 if visible else 0)
        if length + added > limit - 2:
            visible.append("…")
            break
        visible.append(line)
        length += added
    return "\n".join(visible)


def _split_readable_content(
    content: str, first_limit: int, later_limit: int = DISCORD_FIELD_LIMIT
) -> tuple[str, ...]:
    if not content:
        return ("*Nothing is written here.*",)
    pages: list[str] = []
    remaining = content
    limit = first_limit
    while remaining:
        cut = min(len(remaining), limit)
        if cut < len(remaining):
            newline = remaining.rfind("\n", 0, cut + 1)
            space = remaining.rfind(" ", 0, cut + 1)
            preferred = max(newline, space)
            if preferred >= limit // 2:
                cut = preferred + 1
        pages.append(remaining[:cut])
        remaining = remaining[cut:]
        limit = later_limit
    return tuple(pages)


def readable_field_pages(template: ItemTemplate) -> tuple[str, ...]:
    if template.item_type is not ItemType.READABLE:
        raise ValueError("That item is not readable.")
    description = template.description.strip()
    prefix = (
        f"*{description}*\n\n{READING_SEPARATOR}\n" if description else f"{READING_SEPARATOR}\n"
    )
    written_content = template.content or "*Nothing is written here.*"
    return _split_readable_content(
        f"{prefix}{written_content}", DISCORD_EMBED_DESCRIPTION_LIMIT,
        DISCORD_EMBED_DESCRIPTION_LIMIT,
    )


def readable_embed(template: ItemTemplate, page: int = 0) -> discord.Embed:
    pages = readable_field_pages(template)
    current_page = min(max(0, page), len(pages) - 1)
    embed = discord.Embed(
        title=template.name,
        description=pages[current_page],
        colour=discord.Colour.dark_teal(),
    )
    if len(pages) > 1:
        embed.set_footer(text=f"Page {current_page + 1} / {len(pages)}")
    return embed


def inventory_embed(
    character: Character,
    inventory: InventoryState,
    catalog: ItemCatalog,
    selected_id: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{character.name}'s Inventory",
        colour=discord.Colour.dark_gold(),
    )
    embed.description = (
        f"Storage: **{inventory.current_storage(catalog)}/"
        f"{inventory.storage_capacity(catalog)}**\n"
        f"Carried weight: **{inventory.current_weight(catalog)}**"
    )
    equipment_lines = []
    for slot in EquipmentSlot:
        instance_id = inventory.equipment.get(slot)
        label = (
            _item_label(inventory.item(instance_id), catalog)
            if instance_id is not None
            else "Nude"
            if slot is EquipmentSlot.CLOTHING
            else "Empty"
        )
        equipment_lines.append(f"**{slot.value.replace('_', ' ').title()}** — {label}")
    embed.add_field(name="Equipment", value="\n".join(equipment_lines), inline=False)
    bag_lines = _inventory_lines(inventory, catalog)
    embed.add_field(
        name="Inventory",
        value=_fit_field(bag_lines) if bag_lines else "Empty",
        inline=False,
    )
    if selected_id is not None:
        item = inventory.item(selected_id)
        template = catalog.get(item.template_id)
        details = [template.description, f"Rarity: **{template.rarity}**"]
        if template.item_type is ItemType.WEAPON:
            damage = " + ".join(
                f"{part.amount} {part.damage_type}" for part in template.damage_parts
            )
            details.append(f"Damage: **{damage or '—'}**")
        elif template.item_type is ItemType.ARMOR:
            details.append(f"Protection: **{template.protection}**")
            details.append(f"Dodge: **{template.dodge_penalty:+d}**")
        elif template.item_type is ItemType.CONTAINER:
            details.append(
                f"Storage bonus when equipped: **+{template.capacity or 0}**"
            )
        embed.add_field(
            name=f"Selected: {_item_label(item, catalog)}",
            value="\n".join(details),
            inline=False,
        )
    return embed


def inventory_embeds(
    character: Character,
    inventory: InventoryState,
    catalog: ItemCatalog,
    selected_id: str | None = None,
    reading_id: str | None = None,
    reading_page: int = 0,
) -> list[discord.Embed]:
    embeds = [
        inventory_embed(
            character,
            inventory,
            catalog,
            selected_id if reading_id is None else None,
        )
    ]
    if reading_id is not None:
        item = inventory.item(reading_id)
        embeds.append(readable_embed(catalog.get(item.template_id), reading_page))
    return embeds


class InventoryOwnedView(discord.ui.View):
    def __init__(self, service: InventoryService, user_id: int, character_id: int) -> None:
        super().__init__(timeout=15 * 60)
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
        options = [
            discord.SelectOption(
                label=_item_label(item, owner_view.service.catalog)[:100],
                value=item.instance_id,
                description=owner_view.service.catalog.get(item.template_id).rarity[:100],
                default=item.instance_id == owner_view.selected_id,
            )
            for item in inventory.items[start : start + 25]
        ]
        super().__init__(
            placeholder="Select an item",
            options=options or [
                discord.SelectOption(label="Inventory is empty", value="empty")
            ],
            disabled=not options,
            row=0,
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
        await show_inventory(
            interaction,
            self.owner_view.service,
            character,
            selected_id=selected_id,
            page=self.owner_view.page,
            reading_id=reading_id,
            reading_page=0,
            edit=True,
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
    ) -> None:
        super().__init__(service, user_id, character_id)
        self.selected_id = selected_id
        self.page = page
        self.reading_id = reading_id
        self.reading_page = reading_page
        self.page_count = max(1, (len(inventory.items) + 24) // 25)
        self.add_item(InventoryItemSelect(self, inventory))
        self.previous_page.disabled = page <= 0
        self.next_page.disabled = page >= self.page_count - 1
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
        self.equip_button.disabled = not can_equip or is_equipped
        self.unequip_button.disabled = not is_equipped
        self.use_button.disabled = (
            template is None or template.item_type is not ItemType.CONSUMABLE
        )
        self.read_button.disabled = (
            template is None or template.item_type is not ItemType.READABLE
        )
        if reading_id is None:
            self.remove_item(self.reading_previous_button)
            self.remove_item(self.reading_page_button)
            self.remove_item(self.reading_next_button)
        else:
            self.read_button.label = "Close reading"
            self.read_button.style = discord.ButtonStyle.secondary
            self.read_button.disabled = False
            reading_template = service.read(self.character(), reading_id)
            reading_pages = readable_field_pages(reading_template)
            self.reading_page = min(max(0, reading_page), len(reading_pages) - 1)
            self.reading_previous_button.disabled = self.reading_page == 0
            self.reading_next_button.disabled = self.reading_page >= len(reading_pages) - 1
            self.reading_page_button.label = (
                f"Page {self.reading_page + 1} / {len(reading_pages)}"
            )
            self.reading_page_button.disabled = True
            if len(reading_pages) == 1:
                self.remove_item(self.reading_previous_button)
                self.remove_item(self.reading_page_button)
                self.remove_item(self.reading_next_button)

    async def _run(self, interaction: discord.Interaction, action: str) -> None:
        if self.selected_id is None:
            await interaction.response.send_message(
                "Select an item first.", ephemeral=True
            )
            return
        character = self.character()
        try:
            if action == "equip":
                self.service.equip(character, self.selected_id)
            elif action == "unequip":
                self.service.unequip(character, self.selected_id)
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
        await show_inventory(
            interaction,
            self.service,
            character,
            selected_id=selected,
            page=self.page,
            edit=True,
        )

    @discord.ui.button(label="Equip", style=discord.ButtonStyle.success, row=1)
    async def equip_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "equip")

    @discord.ui.button(label="Unequip", style=discord.ButtonStyle.secondary, row=1)
    async def unequip_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "unequip")

    @discord.ui.button(label="Use", style=discord.ButtonStyle.danger, row=1)
    async def use_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run(interaction, "use")

    @discord.ui.button(label="Read", style=discord.ButtonStyle.primary, row=1)
    async def read_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if self.reading_id is not None:
            await show_inventory(
                interaction,
                self.service,
                self.character(),
                selected_id=self.selected_id,
                page=self.page,
                edit=True,
            )
            return
        if self.selected_id is None:
            await interaction.response.send_message(
                "Select a readable item first.", ephemeral=True
            )
            return
        try:
            self.service.read(self.character(), self.selected_id)
        except (InventoryError, ValueError) as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.selected_id,
            reading_page=0,
            edit=True,
        )

    @discord.ui.button(label="Back to sheet", style=discord.ButtonStyle.secondary, row=1)
    async def back_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        from .character import CharacterSheetView

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
        forget_open_inventory(self.user_id, self.character_id)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=2)
    async def previous_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await show_inventory(
            interaction,
            self.service,
            self.character(),
            page=max(0, self.page - 1),
            edit=True,
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=2)
    async def next_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await show_inventory(
            interaction,
            self.service,
            self.character(),
            page=min(self.page_count - 1, self.page + 1),
            edit=True,
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=3)
    async def reading_previous_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.reading_id,
            reading_page=max(0, self.reading_page - 1),
            edit=True,
        )

    @discord.ui.button(label="Page", style=discord.ButtonStyle.secondary, row=3)
    async def reading_page_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        del interaction

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, row=3)
    async def reading_next_button(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await show_inventory(
            interaction,
            self.service,
            self.character(),
            selected_id=self.selected_id,
            page=self.page,
            reading_id=self.reading_id,
            reading_page=self.reading_page + 1,
            edit=True,
        )


@dataclass(slots=True)
class OpenInventory:
    service: InventoryService
    character_id: int
    message: discord.InteractionMessage
    selected_id: str | None
    page: int
    reading_id: str | None
    reading_page: int


_OPEN_INVENTORIES: dict[int, OpenInventory] = {}


def forget_open_inventory(user_id: int, character_id: int | None = None) -> None:
    session = _OPEN_INVENTORIES.get(user_id)
    if session is not None and (
        character_id is None or session.character_id == character_id
    ):
        _OPEN_INVENTORIES.pop(user_id, None)


async def refresh_open_inventory(user_id: int, character_id: int) -> None:
    """Refresh the user's latest private inventory message, if it is still open."""
    session = _OPEN_INVENTORIES.get(user_id)
    if session is None or session.character_id != character_id:
        return
    character = session.service.database.get_character_by_id(
        user_id, session.character_id
    )
    if character is None:
        forget_open_inventory(user_id)
        return
    inventory = session.service.database.get_character_inventory(session.character_id)
    selected_id = (
        session.selected_id
        if any(item.instance_id == session.selected_id for item in inventory.items)
        else None
    )
    reading_id = (
        session.reading_id
        if any(item.instance_id == session.reading_id for item in inventory.items)
        else None
    )
    page_count = max(1, (len(inventory.items) + 24) // 25)
    page = min(session.page, page_count - 1)
    view = InventoryView(
        session.service,
        user_id,
        session.character_id,
        inventory,
        selected_id,
        page,
        reading_id,
        session.reading_page if reading_id is not None else 0,
    )
    try:
        await session.message.edit(
            embeds=inventory_embeds(
                character,
                inventory,
                session.service.catalog,
                selected_id,
                reading_id,
                view.reading_page if reading_id is not None else 0,
            ),
            view=view,
        )
    except discord.HTTPException:
        forget_open_inventory(user_id)
        return
    session.selected_id = selected_id
    session.page = page
    session.reading_id = reading_id
    session.reading_page = view.reading_page if reading_id is not None else 0


async def show_inventory(
    interaction: discord.Interaction,
    service: InventoryService,
    character: Character,
    *,
    selected_id: str | None = None,
    page: int = 0,
    reading_id: str | None = None,
    reading_page: int = 0,
    edit: bool = False,
) -> None:
    inventory = service.database.get_character_inventory(character.character_id)
    embeds = inventory_embeds(
        character,
        inventory,
        service.catalog,
        selected_id,
        reading_id,
        reading_page,
    )
    view = InventoryView(
        service,
        character.discord_user_id,
        character.character_id,
        inventory,
        selected_id,
        page,
        reading_id,
        reading_page,
    )
    if edit:
        await interaction.response.edit_message(embeds=embeds, attachments=[], view=view)
        message = interaction.message
    else:
        await interaction.response.send_message(embeds=embeds, view=view, ephemeral=True)
        message = await interaction.original_response()
    if message is not None:
        _OPEN_INVENTORIES[character.discord_user_id] = OpenInventory(
            service,
            character.character_id,
            message,
            selected_id,
            page,
            reading_id,
            view.reading_page,
        )


class InventoryCommands(commands.Cog):
    def __init__(self, database, catalog: ItemCatalog | None = None) -> None:
        self.catalog = catalog or ItemCatalog.load(DEFAULT_ITEM_CATALOG_PATH)
        self.service = InventoryService(database, self.catalog)

    @app_commands.command(name="inventory", description="Open your active inventory privately.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        character = self.service.database.get_character(interaction.user.id)
        if character is None or character.character_id is None:
            await interaction.response.send_message(
                "You do not have an active character. Use `/character manage` first.",
                ephemeral=True,
            )
            return
        await show_inventory(interaction, self.service, character)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InventoryCommands(bot.database))
