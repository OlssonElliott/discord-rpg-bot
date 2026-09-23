"""Connection request routing for the local DM dashboard API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...world.dungeon import ConnectionType, TrapDamageType, TrapState
from ..parsing.request import (
    parse_boolean,
    parse_integer,
    parse_optional_text,
    parse_text,
)
from ..parsing.connection import (
    parse_connection_type,
    parse_trap_damage_type,
    parse_trap_state,
    validate_door_lock,
    validate_door_open,
    validate_trap,
)

if TYPE_CHECKING:
    from ..api import DashboardAPI


JsonObject = dict[str, Any]
ApiResponse = tuple[int, JsonObject | list[JsonObject]]


def handle_connection_request(
    api: "DashboardAPI",
    method: str,
    path: str,
    body: JsonObject,
) -> ApiResponse | None:
    """Handle connection, door, lock, and trap routes."""
    if path == "/api/connections" and method == "POST":
        exit_name = parse_text(body, "exit_name")
        connection_type = parse_connection_type(
            body,
            default=ConnectionType.HALLWAY,
        )
        is_locked = parse_boolean(body, "is_locked", default=False)
        is_broken = parse_boolean(body, "is_broken", default=False)
        has_lock = parse_boolean(
            body,
            "has_lock",
            default=is_locked or is_broken,
        )
        unlock_difficulty = (
            parse_integer(body, "unlock_difficulty", default=10)
            if is_locked
            else None
        )
        validate_door_lock(
            connection_type,
            has_lock,
            is_locked,
            is_broken,
            unlock_difficulty,
        )
        is_open = parse_boolean(body, "is_open", default=False)
        validate_door_open(
            connection_type,
            is_open,
            is_locked,
        )
        has_trap = parse_boolean(body, "has_trap", default=False)
        trap_state = (
            parse_trap_state(body, default=TrapState.ARMED)
            if has_trap
            else None
        )
        trap_detection_difficulty = (
            parse_integer(
                body,
                "trap_detection_difficulty",
                default=10,
            )
            if has_trap
            else None
        )
        trap_disarm_difficulty = (
            parse_integer(
                body,
                "trap_disarm_difficulty",
                default=10,
            )
            if has_trap
            else None
        )
        trap_damage_type = (
            parse_trap_damage_type(
                body,
                default=TrapDamageType.PHYSICAL,
            )
            if has_trap
            else None
        )
        trap_damage = (
            parse_integer(body, "trap_damage", default=1)
            if has_trap
            else None
        )
        validate_trap(
            has_trap,
            trap_detection_difficulty,
            trap_disarm_difficulty,
            trap_damage_type,
            trap_damage,
        )
        bidirectional = parse_boolean(
            body,
            "bidirectional",
            default=True,
        )
        return_exit_name = (
            parse_optional_text(body, "return_exit_name") or exit_name
            if bidirectional
            else None
        )
        source_room_id = parse_text(body, "source_room_id")
        connection = api.world.connect_rooms(
            source_room_id,
            exit_name,
            parse_text(body, "destination_room_id"),
            return_exit_name=return_exit_name,
            connection_type=connection_type,
            has_lock=has_lock,
            is_locked=is_locked,
            is_broken=is_broken,
            is_open=is_open,
            unlock_difficulty=unlock_difficulty,
            has_trap=has_trap,
            trap_state=trap_state,
            trap_detection_difficulty=trap_detection_difficulty,
            trap_disarm_difficulty=trap_disarm_difficulty,
            trap_damage_type=trap_damage_type,
            trap_damage=trap_damage,
        )
        if has_trap and trap_damage is not None:
            api._connection_trap_damage[
                (source_room_id, exit_name)
            ] = trap_damage
        return 201, {
            "connection_id": connection.id,
            "source_room_id": body["source_room_id"],
            "exit_name": exit_name,
            "destination_room_id": body["destination_room_id"],
            "return_exit_name": return_exit_name,
            "bidirectional": bidirectional,
            "connection_type": connection_type.value,
            "has_lock": has_lock,
            "is_locked": is_locked,
            "is_broken": is_broken,
            "is_open": is_open,
            "unlock_difficulty": unlock_difficulty,
            "has_trap": has_trap,
            "trap_state": (
                trap_state.value
                if trap_state is not None
                else None
            ),
            "trap_detection_difficulty": trap_detection_difficulty,
            "trap_disarm_difficulty": trap_disarm_difficulty,
            "trap_damage_type": (
                trap_damage_type.value
                if trap_damage_type is not None
                else None
            ),
            "trap_damage": trap_damage,
        }

    if path == "/api/connections" and method == "PATCH":
        source_room_id = parse_text(body, "source_room_id")
        exit_name = parse_text(body, "exit_name")
        bidirectional = parse_boolean(
            body,
            "bidirectional",
            default=True,
        )
        return_exit_name = (
            parse_optional_text(body, "return_exit_name") or exit_name
            if bidirectional
            else None
        )
        connection_type = (
            parse_connection_type(body)
            if "connection_type" in body
            else None
        )
        open_was_supplied = "is_open" in body
        is_open = parse_boolean(body, "is_open", default=False)
        lock_was_supplied = (
            "has_lock" in body
            or "is_locked" in body
            or "is_broken" in body
            or "unlock_difficulty" in body
        )
        is_locked = parse_boolean(body, "is_locked", default=False)
        is_broken = parse_boolean(body, "is_broken", default=False)
        has_lock = parse_boolean(
            body,
            "has_lock",
            default=is_locked or is_broken,
        )
        unlock_difficulty = (
            parse_integer(body, "unlock_difficulty", default=10)
            if is_locked
            else None
        )
        trap_was_supplied = any(
            field in body
            for field in (
                "has_trap",
                "trap_state",
                "trap_detection_difficulty",
                "trap_disarm_difficulty",
                "trap_damage_type",
                "trap_damage",
            )
        )
        has_trap = parse_boolean(body, "has_trap", default=False)
        trap_state = (
            parse_trap_state(body, default=TrapState.ARMED)
            if has_trap
            else None
        )
        trap_detection_difficulty = (
            parse_integer(
                body,
                "trap_detection_difficulty",
                default=10,
            )
            if has_trap
            else None
        )
        trap_disarm_difficulty = (
            parse_integer(
                body,
                "trap_disarm_difficulty",
                default=10,
            )
            if has_trap
            else None
        )
        trap_damage_type = (
            parse_trap_damage_type(
                body,
                default=TrapDamageType.PHYSICAL,
            )
            if has_trap
            else None
        )
        trap_damage = (
            parse_integer(body, "trap_damage", default=1)
            if has_trap
            else None
        )
        if is_locked and not 1 <= unlock_difficulty <= 30:
            raise ValueError(
                "Unlock difficulty must be an integer from 1 to 30."
            )
        if connection_type is not None:
            validate_door_lock(
                connection_type,
                has_lock,
                is_locked,
                is_broken,
                unlock_difficulty,
            )
            validate_door_open(
                connection_type,
                is_open,
                is_locked,
            )
        elif is_open and is_locked:
            raise ValueError("A locked door cannot be open.")
        if trap_was_supplied:
            validate_trap(
                has_trap,
                trap_detection_difficulty,
                trap_disarm_difficulty,
                trap_damage_type,
                trap_damage,
            )
        api.world.set_connection_direction(
            source_room_id,
            exit_name,
            bidirectional=bidirectional,
            return_exit_name=return_exit_name,
        )
        if connection_type is not None:
            api.world.set_connection_type(
                source_room_id,
                exit_name,
                connection_type,
            )
        if lock_was_supplied:
            api.world.set_connection_lock(
                source_room_id,
                exit_name,
                has_lock=has_lock,
                is_locked=is_locked,
                is_broken=is_broken,
                unlock_difficulty=unlock_difficulty,
            )
        if open_was_supplied:
            api.world.set_connection_open(
                source_room_id,
                exit_name,
                is_open=is_open,
            )
        if trap_was_supplied:
            api.world.set_connection_trap(
                source_room_id,
                exit_name,
                has_trap=has_trap,
                trap_state=trap_state,
                trap_detection_difficulty=trap_detection_difficulty,
                trap_damage_type=trap_damage_type,
                trap_damage=trap_damage,
            )
            api.world.set_connection_trap_disarm_difficulty(
                source_room_id,
                exit_name,
                trap_disarm_difficulty,
            )
            trap_key = (source_room_id, exit_name)
            if has_trap and trap_damage is not None:
                api._connection_trap_damage[trap_key] = trap_damage
            else:
                api._connection_trap_damage.pop(trap_key, None)
        return 200, {
            "source_room_id": source_room_id,
            "exit_name": exit_name,
            "bidirectional": bidirectional,
            "return_exit_name": return_exit_name,
            **(
                {"is_open": is_open}
                if open_was_supplied
                else {}
            ),
            **(
                {"connection_type": connection_type.value}
                if connection_type is not None
                else {}
            ),
            **(
                {
                    "has_trap": has_trap,
                    "trap_state": (
                        trap_state.value
                        if trap_state is not None
                        else None
                    ),
                    "trap_detection_difficulty": (
                        trap_detection_difficulty
                    ),
                    "trap_disarm_difficulty": (
                        trap_disarm_difficulty
                    ),
                    "trap_damage_type": (
                        trap_damage_type.value
                        if trap_damage_type is not None
                        else None
                    ),
                    "trap_damage": trap_damage,
                }
                if trap_was_supplied
                else {}
            ),
            **(
                {
                    "has_lock": has_lock,
                    "is_locked": is_locked,
                    "is_broken": is_broken,
                    "unlock_difficulty": unlock_difficulty,
                }
                if lock_was_supplied
                else {}
            ),
        }

    if path == "/api/connections" and method == "DELETE":
        source_room_id = parse_text(body, "source_room_id")
        exit_name = parse_text(body, "exit_name")
        api.world.disconnect_connection(
            source_room_id,
            exit_name,
        )
        api._connection_trap_damage.pop(
            (source_room_id, exit_name),
            None,
        )
        return 200, {"deleted": True}

    return None
