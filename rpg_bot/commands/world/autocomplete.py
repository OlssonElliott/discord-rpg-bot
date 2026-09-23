"""Autocomplete and known-connection helpers for world commands."""

from __future__ import annotations

import discord
from discord import app_commands

from ...database import CharacterNotFoundError
from ...world.dungeon import ConnectionType, RoomConnection, TrapState
from ...world import InventoryHolder, Room, WorldError


async def loose_item_autocomplete(
    cog, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest loose items in the active character's current room."""
    # Room inventory formatting is handled here; non-stackable entries are
    # already expanded to quantity-one ItemStacks by WorldService.inventory.
    try:
        room = cog.world.get_character_room(
            cog._active_character_id(interaction.user.id)
        )
    except (CharacterNotFoundError, WorldError):
        return []
    if room is None:
        return []

    query = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []
    for stack in cog.world.inventory(InventoryHolder.room(room.id)):
        if (
            query
            and query not in stack.item.name.casefold()
            and query not in stack.item.id.casefold()
        ):
            continue
        template = cog.world._template_for_world_item(stack.item)
        stackable = (
            template.stackable if template is not None else stack.item.stackable
        )
        label = (
            f"{stack.item.name} x{stack.quantity}"
            if stackable
            else stack.item.name
        )
        choices.append(app_commands.Choice(name=label[:100], value=stack.item.id))
        if len(choices) == 25:
            break
    return choices


async def inventory_item_autocomplete(
    cog, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest droppable, unequipped items from the active inventory with stack counts."""
    try:
        character_id = cog._active_character_id(interaction.user.id)
    except CharacterNotFoundError:
        return []

    inventory = cog.database.get_character_inventory(character_id)
    equipped = set(inventory.equipment.values())
    query = current.casefold().strip()
    stacked = []
    stack_indexes: dict[str, int] = {}
    for item in inventory.items:
        if item.instance_id in equipped:
            continue
        template = cog.world.catalog.get(item.template_id)
        key = item.template_id if template.stackable else item.instance_id
        index = stack_indexes.get(key)
        if index is None:
            stack_indexes[key] = len(stacked)
            stacked.append((item, item.quantity, 1))
        else:
            first_item, quantity, instance_count = stacked[index]
            stacked[index] = (
                first_item, quantity + item.quantity, instance_count + 1
            )

    choices: list[app_commands.Choice[str]] = []
    for item, quantity, instance_count in stacked:
        template = cog.world.catalog.get(item.template_id)
        if (
            query
            and query not in template.name.casefold()
            and query not in template.template_id.casefold()
        ):
            continue
        quantity_suffix = (
            f" x{quantity}" if template.stackable and quantity > 1 else ""
        )
        choices.append(
            app_commands.Choice(
                name=f"{template.name}{quantity_suffix}"[:100],
                value=(
                    template.template_id
                    if template.stackable and instance_count > 1
                    else item.instance_id
                ),
            )
        )
        if len(choices) == 25:
            break
    return choices


async def move_destination_autocomplete(
    cog, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest reachable rooms without revealing hidden connections."""
    try:
        character_id = cog._active_character_id(interaction.user.id)
        room = cog.world.get_character_room(character_id)
    except (CharacterNotFoundError, WorldError):
        return []
    if room is None:
        return []

    reachable_room_ids: set[str] = set()
    for connection in cog.database.list_known_connections(character_id):
        if connection.from_room_id == room.id:
            reachable_room_ids.add(connection.to_room_id)
        elif connection.bidirectional and connection.to_room_id == room.id:
            reachable_room_ids.add(connection.from_room_id)

    query = current.casefold().strip()
    choices = []
    for exit in room.exits:
        if exit.destination_room_id not in reachable_room_ids:
            continue
        destination = cog.database.get_room(exit.destination_room_id)
        if destination is None:
            continue
        destination_is_known = (
            cog.database.get_character_knowledge(
                character_id, exit.destination_room_id
            )
            is not None
        )
        if (
            query
            and query not in exit.name.casefold()
            and (
                not destination_is_known
                or (
                    query not in destination.name.casefold()
                    and query not in destination.id.casefold()
                )
            )
        ):
            continue
        choices.append(
            app_commands.Choice(
                name=(
                    f"{destination.name} — via {exit.name}"
                    if destination_is_known
                    else exit.name.capitalize()
                )[:100],
                value=exit.name,
            )
        )
    return choices[:25]


def known_doors_from_room(
    cog, character_id: int, room: Room
) -> dict[str, tuple[str, RoomConnection]]:
    connections = cog.database.list_known_connections(character_id)
    doors: dict[str, tuple[str, RoomConnection]] = {}
    for room_exit in room.exits:
        for connection in connections:
            if connection.connection_type is not ConnectionType.DOOR:
                continue
            forward = (
                connection.from_room_id == room.id
                and connection.to_room_id == room_exit.destination_room_id
            )
            reverse = (
                connection.bidirectional
                and connection.to_room_id == room.id
                and connection.from_room_id == room_exit.destination_room_id
            )
            if forward or reverse:
                doors[room_exit.name.casefold()] = (room_exit.name, connection)
                break
    return doors


def known_connections_from_room(
    cog, character_id: int, room: Room
) -> dict[str, tuple[str, RoomConnection]]:
    connections = cog.database.list_known_connections(character_id)
    result: dict[str, tuple[str, RoomConnection]] = {}
    for room_exit in room.exits:
        for connection in connections:
            forward = (
                connection.from_room_id == room.id
                and connection.to_room_id == room_exit.destination_room_id
            )
            reverse = (
                connection.bidirectional
                and connection.to_room_id == room.id
                and connection.from_room_id == room_exit.destination_room_id
            )
            if forward or reverse:
                result[room_exit.name.casefold()] = (room_exit.name, connection)
                break
    return result


async def door_exit_autocomplete(
    cog, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest only known door exits from the active character's room."""
    try:
        character_id = cog._active_character_id(interaction.user.id)
        room = cog.world.get_character_room(character_id)
    except (CharacterNotFoundError, WorldError):
        return []
    if room is None:
        return []

    query = current.casefold().strip()
    return [
        app_commands.Choice(name=exit_name.capitalize()[:100], value=exit_name)
        for exit_name, _connection in cog._known_doors_from_room(
            character_id, room
        ).values()
        if not query or query in exit_name.casefold()
    ][:25]


async def disarm_exit_autocomplete(
    cog, interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Suggest armed traps on passages visible from the current room."""
    try:
        character_id = cog._active_character_id(interaction.user.id)
        room = cog.world.get_character_room(character_id)
    except (CharacterNotFoundError, WorldError):
        return []
    if room is None:
        return []

    query = current.casefold().strip()
    choices: list[app_commands.Choice[str]] = []
    for exit_name, connection in cog._known_connections_from_room(
        character_id, room
    ).values():
        if (
            not connection.has_trap
            or connection.trap_state is not TrapState.ARMED
        ):
            continue
        if query and query not in exit_name.casefold():
            continue
        choices.append(
            app_commands.Choice(
                name=exit_name.capitalize()[:100],
                value=exit_name,
            )
        )
    return choices[:25]
