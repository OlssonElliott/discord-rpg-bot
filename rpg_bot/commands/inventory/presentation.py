"""Pure presentation helpers for Discord inventory views."""

from __future__ import annotations

import discord

from ...inventory import (
    EquipmentSlot,
    InventoryState,
    ItemCatalog,
    ItemInstance,
    ItemTemplate,
    ItemType,
)
from ...characters.models import Character


DISCORD_FIELD_LIMIT = 1024
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
READING_SEPARATOR = "──────────"


def _item_label(item: ItemInstance, catalog: ItemCatalog) -> str:
    return _item_label_for_quantity(item, item.quantity, catalog)


def _item_label_for_quantity(
    item: ItemInstance,
    quantity: int,
    catalog: ItemCatalog,
) -> str:
    template = catalog.get(item.template_id)
    quantity_suffix = f" ×{quantity}" if quantity > 1 else ""
    return f"{template.name}{quantity_suffix}"


def _stacked_inventory_items(
    items: list[ItemInstance],
    catalog: ItemCatalog,
) -> list[tuple[ItemInstance, int]]:
    stacked: list[tuple[ItemInstance, int]] = []
    stack_indexes: dict[str, int] = {}
    for item in items:
        template = catalog.get(item.template_id)
        if not template.stackable:
            stacked.append((item, item.quantity))
            continue
        index = stack_indexes.get(item.template_id)
        if index is None:
            stack_indexes[item.template_id] = len(stacked)
            stacked.append((item, item.quantity))
            continue
        first_item, quantity = stacked[index]
        stacked[index] = (first_item, quantity + item.quantity)
    return stacked


def _inventory_lines(
    inventory: InventoryState,
    catalog: ItemCatalog,
) -> list[str]:
    equipped_ids = set(inventory.equipment.values())
    items = [
        item for item in inventory.items if item.instance_id not in equipped_ids
    ]
    lines: list[str] = []
    for item, quantity in _stacked_inventory_items(items, catalog):
        template = catalog.get(item.template_id)
        weight = template.weight * quantity
        capacity_bonus = (
            f" • +{template.capacity or 0} slots when equipped"
            if template.item_type is ItemType.CONTAINER
            else ""
        )
        slot_label = "slot" if template.slot_cost == 1 else "slots"
        lines.append(
            f"• {_item_label_for_quantity(item, quantity, catalog)} • {weight} weight • "
            f"{template.slot_cost} {slot_label}{capacity_bonus}"
        )
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
    coin_weight = inventory.coin_weight()
    coin_weight_text = f" (coins: {coin_weight})" if coin_weight else ""
    embed.description = (
        f"Money: **{inventory.gold} gold • {inventory.silver} silver • "
        f"{inventory.copper} copper**\n"
        f"Storage slots: **{inventory.current_storage(catalog)}/"
        f"{inventory.storage_capacity(catalog)}**\n"
        f"Carried weight: **{inventory.current_weight(catalog)}/"
        f"{inventory.carry_capacity()}**{coin_weight_text}"
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
        details.append(f"Slots: **{template.slot_cost}**")
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
                f"Storage slot bonus when equipped: **+{template.capacity or 0}**"
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
