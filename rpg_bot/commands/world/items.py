"""Item transfer and container command support."""

from __future__ import annotations

import discord

from ...database import CharacterNotFoundError
from ...world import InventoryHolder, ItemStack, WorldError
from ..inventory import refresh_inventory_views


def _stack_text(stack: ItemStack) -> str:
    return f"{stack.quantity} × {stack.item.name}"


async def take(
    cog, interaction: discord.Interaction, item: str, quantity: int | None = None
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        room = cog.world.get_character_room(character.character_id)
        matching_stacks = [] if room is None else [
            stack
            for stack in room.loose_items
            if stack.item.id == item
            or stack.item.name.casefold() == item.casefold()
        ]
        if (
            quantity is None
            and len(matching_stacks) == 1
            and matching_stacks[0].quantity > 1
        ):
            available = matching_stacks[0].quantity

            class TakeQuantityModal(discord.ui.Modal, title="Take item"):
                quantity_input = discord.ui.TextInput(
                    label="Quantity",
                    default="1",
                    required=True,
                    max_length=6,
                )

                async def on_submit(
                    modal_self, modal_interaction: discord.Interaction
                ) -> None:
                    try:
                        requested_quantity = int(
                            str(modal_self.quantity_input.value).strip()
                        )
                    except ValueError:
                        await modal_interaction.response.send_message(
                            "Enter a whole number of at least 1.", ephemeral=True
                        )
                        return
                    if requested_quantity < 1:
                        await modal_interaction.response.send_message(
                            "Enter a whole number of at least 1.", ephemeral=True
                        )
                        return
                    if requested_quantity > available:
                        await modal_interaction.response.send_message(
                            f"Only {available} of that item is available.",
                            ephemeral=True,
                        )
                        return
                    try:
                        moved = cog.world.take_loose_item(
                            character.character_id, item, requested_quantity
                        )
                    except (CharacterNotFoundError, WorldError) as error:
                        await cog._error(modal_interaction, error)
                        return
                    description = f"Took **{_stack_text(moved)}**."
                    await cog._send_character_action(
                        modal_interaction, character, description, description
                    )
                    await refresh_inventory_views(modal_interaction, character)

            await interaction.response.send_modal(TakeQuantityModal())
            return

        requested_quantity = 1 if quantity is None else quantity
        if requested_quantity < 1:
            raise WorldError("Quantity must be at least 1.")
        if (
            len(matching_stacks) == 1
            and requested_quantity > matching_stacks[0].quantity
        ):
            raise WorldError(
                f"Only {matching_stacks[0].quantity} of that item is available."
            )
        moved = cog.world.take_loose_item(
            character.character_id, item, requested_quantity
        )
    except (CharacterNotFoundError, WorldError) as error:
        await cog._error(interaction, error)
        return
    description = f"Took **{_stack_text(moved)}**."
    await cog._send_character_action(
        interaction, character, description, description
    )
    await refresh_inventory_views(interaction, character)


async def drop(
    cog, interaction: discord.Interaction, item: str, quantity: int | None = None
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        inventory = cog.database.get_character_inventory(character.character_id)
        equipped = set(inventory.equipment.values())
        selected = next(
            (
                inventory_item
                for inventory_item in inventory.items
                if inventory_item.instance_id == item
            ),
            None,
        )
        template_id = selected.template_id if selected is not None else item
        stack_items = [
            inventory_item
            for inventory_item in inventory.items
            if inventory_item.template_id == template_id
            and inventory_item.instance_id not in equipped
            and cog.world.catalog.get(inventory_item.template_id).stackable
        ]
        if stack_items:
            available = sum(
                inventory_item.quantity for inventory_item in stack_items
            )
            item_name = cog.world.catalog.get(template_id).name

            def drop_stack(requested_quantity: int) -> str:
                if requested_quantity < 1:
                    raise WorldError("Quantity must be at least 1.")
                if requested_quantity > available:
                    raise WorldError(
                        f"Only {available} of that item is available."
                    )
                remaining = requested_quantity
                for inventory_item in stack_items:
                    if remaining <= 0:
                        break
                    moved_quantity = min(remaining, inventory_item.quantity)
                    cog.world.drop_item(
                        character.character_id,
                        inventory_item.instance_id,
                        moved_quantity,
                    )
                    remaining -= moved_quantity
                return f"Dropped **{requested_quantity} × {item_name}**."

            if quantity is None and available > 1:

                class DropQuantityModal(discord.ui.Modal, title="Drop item"):
                    quantity_input = discord.ui.TextInput(
                        label="Quantity",
                        default="1",
                        required=True,
                        max_length=6,
                    )

                    async def on_submit(
                        modal_self, modal_interaction: discord.Interaction
                    ) -> None:
                        try:
                            requested_quantity = int(
                                str(modal_self.quantity_input.value).strip()
                            )
                        except ValueError:
                            await modal_interaction.response.send_message(
                                "Enter a whole number of at least 1.",
                                ephemeral=True,
                            )
                            return
                        try:
                            description = drop_stack(requested_quantity)
                        except (CharacterNotFoundError, WorldError) as error:
                            await cog._error(modal_interaction, error)
                            return
                        await cog._send_character_action(
                            modal_interaction,
                            character,
                            description,
                            description,
                        )
                        await refresh_inventory_views(
                            modal_interaction, character
                        )

                await interaction.response.send_modal(DropQuantityModal())
                return

            description = drop_stack(1 if quantity is None else quantity)
        else:
            requested_quantity = 1 if quantity is None else quantity
            if requested_quantity > 1:
                template = cog.world.catalog.get(template_id)
                if not template.stackable:
                    matching_items = [
                        inventory_item
                        for inventory_item in inventory.items
                        if inventory_item.template_id == template_id
                        and inventory_item.instance_id not in equipped
                    ]
                    if requested_quantity > len(matching_items):
                        raise WorldError(
                            f"Only {len(matching_items)} × {template.name} is available."
                        )
                    for inventory_item in matching_items[:requested_quantity]:
                        cog.world.drop_item(
                            character.character_id,
                            inventory_item.instance_id,
                            1,
                        )
                    description = (
                        f"Dropped **{requested_quantity} × {template.name}**."
                    )
                    await cog._send_character_action(
                        interaction, character, description, description
                    )
                    return
            moved = cog.world.drop_item(
                character.character_id, item, requested_quantity
            )
            description = f"Dropped **{_stack_text(moved)}**."
    except (CharacterNotFoundError, WorldError) as error:
        await cog._error(interaction, error)
        return
    await cog._send_character_action(
        interaction, character, description, description
    )
    await refresh_inventory_views(interaction, character)


async def loot(cog, interaction: discord.Interaction, container: str) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")
        matches = [
            entity
            for entity in room.containers
            if entity.id == container or entity.name.casefold() == container.casefold()
        ]
        if not matches:
            raise WorldError(f"There is no container named '{container}' here.")
        if len(matches) > 1 and all(entity.id != container for entity in matches):
            raise WorldError("That name is ambiguous; use the container ID.")
        selected = next(
            (entity for entity in matches if entity.id == container), matches[0]
        )
        stacks = cog.world.inventory(InventoryHolder.entity(selected.id))
    except (CharacterNotFoundError, WorldError) as error:
        await cog._error(interaction, error)
        return
    contents = "\n".join(_stack_text(stack) for stack in stacks) or "Empty"
    embed = cog._action_embed(contents)
    embed.title = selected.name
    await cog._send_character_embed(interaction, character, embed)


async def take_from(
    cog,
    interaction: discord.Interaction,
    container: str,
    item: str,
    quantity: int = 1,
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        moved = cog.world.take_from_container(
            character.character_id,
            container,
            item,
            quantity,
        )
    except (CharacterNotFoundError, WorldError) as error:
        await cog._error(interaction, error)
        return
    await cog._send_character_embed(
        interaction,
        character,
        cog._action_embed(f"Took **{_stack_text(moved)}**."),
    )
    await refresh_inventory_views(interaction, character)
