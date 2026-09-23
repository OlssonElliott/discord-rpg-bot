"""Connection request parsing and validation helpers."""

from __future__ import annotations

from typing import Any

from ...world.dungeon import ConnectionType, TrapDamageType, TrapState


JsonObject = dict[str, Any]


def parse_connection_type(
    body: JsonObject,
    *,
    default: ConnectionType | None = None,
) -> ConnectionType:
    """Parse a supported connection type from request data."""
    value = body.get("connection_type")
    if value is None and default is not None:
        return default
    try:
        parsed = ConnectionType(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Connection type must be door or hallway."
        ) from error
    if parsed not in (
        ConnectionType.DOOR,
        ConnectionType.HALLWAY,
    ):
        raise ValueError(
            "Connection type must be door or hallway."
        )
    return parsed


def validate_door_lock(
    connection_type: ConnectionType,
    has_lock: bool,
    is_locked: bool,
    is_broken: bool,
    unlock_difficulty: int | None,
) -> None:
    """Validate lock state for a connection."""
    if has_lock and connection_type is not ConnectionType.DOOR:
        raise ValueError(
            "Only door connections can have a lock."
        )
    if (is_locked or is_broken) and not has_lock:
        raise ValueError(
            "A door without a lock cannot be locked or broken."
        )
    if is_locked and is_broken:
        raise ValueError(
            "A broken lock cannot also be locked."
        )
    if is_locked and (
        unlock_difficulty is None
        or not 1 <= unlock_difficulty <= 30
    ):
        raise ValueError(
            "Unlock difficulty must be an integer from 1 to 30."
        )


def validate_door_open(
    connection_type: ConnectionType,
    is_open: bool,
    is_locked: bool,
) -> None:
    """Validate open state for a connection."""
    if is_open and connection_type is not ConnectionType.DOOR:
        raise ValueError(
            "Only door connections can be open."
        )
    if is_open and is_locked:
        raise ValueError(
            "A locked door cannot be open."
        )


def parse_trap_damage_type(
    body: JsonObject,
    *,
    default: TrapDamageType,
) -> TrapDamageType:
    """Parse a trap damage type from request data."""
    value = body.get("trap_damage_type", default.value)
    if isinstance(value, str):
        value = value.strip().casefold()
    try:
        return TrapDamageType(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(
            item.value for item in TrapDamageType
        )
        raise ValueError(
            f"Trap damage type must be one of: {allowed}."
        ) from error


def parse_trap_state(
    body: JsonObject,
    *,
    default: TrapState,
) -> TrapState:
    """Parse a trap state from request data."""
    value = body.get("trap_state", default.value)
    try:
        return TrapState(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Trap state must be armed, disarmed, or triggered."
        ) from error


def validate_trap(
    has_trap: bool,
    trap_detection_difficulty: int | None,
    trap_disarm_difficulty: int | None,
    trap_damage_type: TrapDamageType | None,
    trap_damage: int | None,
) -> None:
    """Validate trap configuration."""
    if not has_trap:
        return
    if (
        trap_detection_difficulty is None
        or not 1 <= trap_detection_difficulty <= 30
    ):
        raise ValueError(
            "Trap detection difficulty must be an integer from 1 to 30."
        )
    if (
        trap_disarm_difficulty is None
        or not 1 <= trap_disarm_difficulty <= 30
    ):
        raise ValueError(
            "Trap disarm difficulty must be an integer from 1 to 30."
        )
    if trap_damage_type is None:
        raise ValueError(
            "Trap damage type is required."
        )
    if trap_damage is None or trap_damage <= 0:
        raise ValueError(
            "Trap damage must be a positive integer."
        )
