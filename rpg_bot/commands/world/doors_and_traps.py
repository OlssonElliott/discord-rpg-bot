"""Door, lock, and trap command support."""

from __future__ import annotations

import discord

from ...database import CharacterNotFoundError
from ...world.dungeon import TrapState
from ...world import WorldError
from ..inventory import refresh_inventory_views


async def set_door_state(
    cog,
    interaction: discord.Interaction,
    door_exit: str,
    *,
    is_open: bool,
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")
        door = cog._known_doors_from_room(character.character_id, room).get(
            door_exit.casefold().strip()
        )
        if door is None:
            raise WorldError(f"There is no known door at exit '{door_exit}'.")
        exit_name, connection = door

        changed = False
        if is_open and connection.is_open:
            description = (
                f"{character.name} tries to open the door, but realizes it's already open."
            )
        elif not is_open and not connection.is_open:
            description = (
                f"{character.name} tries to close the door, but realizes it's already closed."
            )
        elif is_open and connection.is_locked:
            description = f"{character.name} tries to open the door, but it is locked."
        else:
            cog.world.set_connection_open(room.id, exit_name, is_open=is_open)
            changed = True
            description = (
                f"{character.name} opens the door."
                if is_open
                else f"{character.name} closes the door."
            )
    except (CharacterNotFoundError, WorldError, ValueError) as error:
        await cog._error(interaction, error)
        return

    await cog._send_character_action(
        interaction,
        character,
        description,
        "Door interaction resolved.",
    )
    if changed and await cog._refresh_existing_map(character.character_id):
        cog.database.clear_player_map_refresh(character.character_id)


async def lockpick(
    cog, interaction: discord.Interaction, door_exit: str
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")

        door = cog._known_doors_from_room(character.character_id, room).get(
            door_exit.casefold().strip()
        )
        if door is None:
            raise WorldError(f"There is no known door at exit '{door_exit}'.")

        exit_name, connection = door
        if not connection.has_lock:
            raise WorldError("That door has no lock to pick.")
        if connection.is_broken:
            raise WorldError("That lock is broken.")
        if not connection.is_locked:
            raise WorldError("That door is already unlocked.")

        if not cog.database.character_has_usable_item(
            character.character_id, "lockpicks"
        ):
            raise WorldError("You need usable lockpicks to pick that lock.")

        difficulty = connection.unlock_difficulty or 10
        dexterity = cog.database.get_character_attribute(
            character.character_id, "dexterity"
        )
        dexterity_bonus = (dexterity - 10) // 2
        stealth_bonus = cog.database.get_character_skill_rank(
            character.character_id, "stealth"
        )
        roll = cog._roll_d20()
        total = roll + dexterity_bonus + stealth_bonus
        succeeded = total >= difficulty

        if succeeded:
            cog.world.set_connection_lock(
                room.id,
                exit_name,
                has_lock=True,
                is_locked=False,
            )
            description = (
                f"{character.name} works at the lock until it gives with a quiet click."
            )
        else:
            cog.database.break_character_item(character.character_id, "lockpicks")
            description = (
                f"{character.name} works at the lock, but the mechanism refuses to give. "
                "The lockpicks snap under the strain."
            )

        modifiers = [f"Dexterity {dexterity_bonus:+d}"]
        if stealth_bonus:
            modifiers.append(f"Stealth {stealth_bonus:+d}")
        result = "succeeded" if succeeded else "failed"
        confirmation = (
            f"Lockpick {result}: **{total}** "
            f"(d20 {roll}, {', '.join(modifiers)})."
            + (" Your lockpicks broke." if not succeeded else "")
        )
    except (CharacterNotFoundError, WorldError, ValueError) as error:
        await cog._error(interaction, error)
        return

    await cog._send_character_action(
        interaction, character, description, confirmation
    )
    if succeeded and await cog._refresh_existing_map(character.character_id):
        cog.database.clear_player_map_refresh(character.character_id)


async def search_traps(cog, interaction: discord.Interaction) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")

        insight = cog.database.get_character_attribute(
            character.character_id, "insight"
        )
        insight_bonus = (insight - 10) // 2
        roll = cog._roll_d20()
        total = roll + insight_bonus
        detected: list[str] = []

        for exit_name, _connection in cog._known_connections_from_room(
            character.character_id, room
        ).values():
            (
                connection_id,
                has_trap,
                trap_state,
                detection_difficulty,
                _disarm_difficulty,
            ) = cog.database.get_connection_trap_details(room.id, exit_name)
            if (
                not has_trap
                or trap_state is TrapState.TRIGGERED
                or cog.database.character_knows_trap(
                    character.character_id, connection_id
                )
            ):
                continue
            if total >= (detection_difficulty or 10):
                cog.database.mark_trap_detected(
                    character.character_id, connection_id
                )
                detected.append(exit_name)
    except (CharacterNotFoundError, WorldError, ValueError) as error:
        await cog._error(interaction, error)
        return

    message = (
        "You detect a trap at "
        + ", ".join(f"**{exit_name}**" for exit_name in detected)
        + "."
        if detected
        else "You do not detect any traps."
    )
    await interaction.response.send_message(
        f"{message}\nInsight check: **{total}** "
        f"(d20 {roll}, Insight {insight_bonus:+d}).",
        ephemeral=True,
    )
    if detected and await cog._refresh_existing_map(character.character_id):
        cog.database.clear_player_map_refresh(character.character_id)


async def disarm(
    cog,
    interaction: discord.Interaction,
    trap_exit: str,
) -> None:
    try:
        character = cog._active_character(interaction.user.id)
        assert character.character_id is not None
        room = cog.world.get_character_room(character.character_id)
        if room is None:
            raise WorldError("Your character has not been placed in a room yet.")

        known = cog._known_connections_from_room(
            character.character_id, room
        ).get(trap_exit.casefold().strip())
        if known is None:
            raise WorldError(f"There is no known exit '{trap_exit}'.")

        exit_name, visible_connection = known
        (
            connection_id,
            has_trap,
            trap_state,
            _detection_difficulty,
            disarm_difficulty,
        ) = cog.database.get_connection_trap_details(room.id, exit_name)
        if (
            not has_trap
            or trap_state is not TrapState.ARMED
            or not visible_connection.has_trap
        ):
            raise WorldError("There is no armed trap there to disarm.")

        if not cog.database.character_has_usable_item(
            character.character_id, "trap_disarm_kit"
        ):
            raise WorldError("You need a usable Trap Disarm Kit to disarm that trap.")

        dexterity = cog.database.get_character_attribute(
            character.character_id, "dexterity"
        )
        dexterity_bonus = (dexterity - 10) // 2
        roll = cog._roll_d20()
        total = roll + dexterity_bonus
        succeeded = total >= (disarm_difficulty or 10)
        if succeeded:
            cog.world.set_connection_trap_state(
                connection_id, TrapState.DISARMED
            )
        else:
            cog.database.break_character_item(
                character.character_id, "trap_disarm_kit"
            )

        confirmation = (
            f"Disarm {'succeeded' if succeeded else 'failed'}: "
            f"**{total}** (d20 {roll}, Dexterity {dexterity_bonus:+d})."
            + (" Your Trap Disarm Kit broke." if not succeeded else "")
        )
        description = (
            f"{character.name} carefully disarms the trap."
            if succeeded
            else (
                f"{character.name} works at the trap, but fails to disarm it. "
                "The disarm kit breaks in the attempt."
            )
        )
    except (CharacterNotFoundError, WorldError, ValueError) as error:
        await cog._error(interaction, error)
        return

    await cog._send_character_action(
        interaction, character, description, confirmation
    )
    if not succeeded:
        await refresh_inventory_views(interaction, character)
    if succeeded and await cog._refresh_existing_map(character.character_id):
        cog.database.clear_player_map_refresh(character.character_id)
