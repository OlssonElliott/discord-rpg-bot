"""Room connection creation and lifecycle persistence."""

from __future__ import annotations

from uuid import uuid4

from ...world.dungeon import ConnectionType, RoomConnection, TrapDamageType, TrapState
from ...world import InvalidMovementError, NotFoundError


class DatabaseConnectionsMixin:
    """Persist creation, direction changes, and removal of room connections."""

    def connect_rooms(
        self,
        room_id: str,
        exit_name: str,
        destination_room_id: str,
        *,
        return_exit_name: str | None = None,
        connection_type: ConnectionType = ConnectionType.PASSAGE,
        hidden: bool = False,
        has_lock: bool = False,
        is_locked: bool = False,
        unlock_difficulty: int | None = None,
        is_broken: bool = False,
        is_open: bool = False,
        has_trap: bool = False,
        trap_state: TrapState | None = None,
        trap_detection_difficulty: int | None = None,
        trap_disarm_difficulty: int | None = None,
        trap_damage_type: TrapDamageType | None = None,
        trap_damage: int | None = None,
    ) -> RoomConnection:
        exit_name = self._clean_name(exit_name, "Exit name")
        if return_exit_name is not None:
            return_exit_name = self._clean_name(return_exit_name, "Return exit name")
        unlock_difficulty = self._validate_connection_lock(
            connection_type, has_lock, is_locked, is_broken, unlock_difficulty
        )
        self._validate_connection_open(connection_type, is_open, is_locked)
        trap_state, trap_detection_difficulty, trap_damage_type, trap_damage = (
            self._validate_connection_trap(
                connection_type,
                has_trap,
                trap_state,
                trap_detection_difficulty,
                trap_damage_type,
                trap_damage,
            )
        )
        if has_trap:
            trap_disarm_difficulty = trap_disarm_difficulty or 10
            if not 1 <= trap_disarm_difficulty <= 30:
                raise ValueError(
                    "Trap disarm difficulty must be an integer from 1 to 30."
                )
        else:
            trap_disarm_difficulty = None
        with self._connect() as connection:
            source_room = self._require_room(connection, room_id)
            destination_room = self._require_room(connection, destination_room_id)
            if source_room["area_id"] != destination_room["area_id"]:
                raise InvalidMovementError("Rooms in different areas cannot be connected.")
            duplicate_destination = connection.execute(
                """
                SELECT 1 FROM room_exits
                WHERE room_id = ? AND destination_room_id = ?
                """,
                (room_id, destination_room_id),
            ).fetchone()
            if duplicate_destination:
                raise InvalidMovementError("Those rooms are already connected.")
            duplicate_name = connection.execute(
                """
                SELECT 1 FROM room_exits
                WHERE room_id = ? AND name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if duplicate_name:
                raise InvalidMovementError(
                    f"This room already has an exit named '{exit_name}'. "
                    "Choose a different exit name."
                )
            if return_exit_name is not None:
                reverse_destination = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND destination_room_id = ?
                    """,
                    (destination_room_id, room_id),
                ).fetchone()
                if reverse_destination:
                    raise InvalidMovementError("Those rooms are already connected.")
                reverse_name = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                    """,
                    (destination_room_id, return_exit_name),
                ).fetchone()
                if reverse_name:
                    raise InvalidMovementError(
                        f"The destination already has an exit named "
                        f"'{return_exit_name}'. Choose a different return exit name."
                    )
            connection.execute(
                """
                INSERT INTO room_exits (room_id, name, destination_room_id)
                VALUES (?, ?, ?)
                """,
                (room_id, exit_name, destination_room_id),
            )
            if return_exit_name is not None:
                connection.execute(
                    """
                    INSERT INTO room_exits (room_id, name, destination_room_id)
                    VALUES (?, ?, ?)
                    """,
                    (destination_room_id, return_exit_name, room_id),
                )
            connection_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO room_connections (
                    id, from_room_id, to_room_id, exit_name, return_exit_name,
                    connection_type, hidden, bidirectional, is_locked,
                    is_broken, is_open, unlock_difficulty, has_lock, has_trap,
                    trap_state, trap_detection_difficulty,
                    trap_disarm_difficulty, trap_damage_type, trap_damage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    room_id,
                    destination_room_id,
                    exit_name,
                    return_exit_name,
                    connection_type.value,
                    int(hidden),
                    int(return_exit_name is not None),
                    int(is_locked),
                    int(is_broken),
                    int(is_open),
                    unlock_difficulty,
                    int(has_lock),
                    int(has_trap),
                    trap_state.value if trap_state is not None else None,
                    trap_detection_difficulty,
                    trap_disarm_difficulty,
                    trap_damage_type.value if trap_damage_type is not None else None,
                    trap_damage,
                ),
            )
            if not hidden:
                visible_endpoints = [room_id]
                if return_exit_name is not None:
                    visible_endpoints.append(destination_room_id)
                placeholders = ", ".join("?" for _ in visible_endpoints)
                present_characters = connection.execute(
                    f"""
                    SELECT id, current_room_id
                    FROM characters
                    WHERE is_archived = 0
                      AND current_room_id IN ({placeholders})
                    """,
                    visible_endpoints,
                ).fetchall()
                for character_row in present_characters:
                    character_id = character_row["id"]
                    current_room_id = character_row["current_room_id"]
                    adjacent_room_id = (
                        destination_room_id
                        if current_room_id == room_id
                        else room_id
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO character_known_connections (
                            character_id, connection_id
                        ) VALUES (?, ?)
                        """,
                        (character_id, connection_id),
                    )
                    if connection_type is ConnectionType.DOOR and not is_open:
                        continue
                    connection.execute(
                        """
                        INSERT INTO character_room_knowledge (
                            character_id, room_id, state, source
                        ) VALUES (?, ?, 'known', 'discovered')
                        ON CONFLICT(character_id, room_id) DO NOTHING
                        """,
                        (character_id, adjacent_room_id),
                    )
                for endpoint_room_id in visible_endpoints:
                    self._queue_map_refresh_for_room(connection, endpoint_room_id)
        return RoomConnection(
            connection_id,
            room_id,
            destination_room_id,
            connection_type,
            hidden,
            return_exit_name is not None,
            has_lock,
            is_locked,
            unlock_difficulty,
            is_broken,
            is_open,
            has_trap,
            trap_state,
            trap_detection_difficulty,
            trap_disarm_difficulty,
            trap_damage_type,
            trap_damage,
        )

    def disconnect_rooms(self, room_id: str, exit_name: str) -> None:
        """Backward-compatible alias for removing a complete passage."""
        self.disconnect_connection(room_id, exit_name)

    def set_connection_direction(
        self,
        room_id: str,
        exit_name: str,
        *,
        bidirectional: bool,
        return_exit_name: str | None = None,
    ) -> None:
        """Change a canonical connection between one-way and two-way."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, exit_name,
                       return_exit_name, bidirectional
                FROM room_connections
                WHERE from_room_id = ? AND exit_name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )

            if row["bidirectional"] and row["return_exit_name"]:
                connection.execute(
                    """
                    DELETE FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                      AND destination_room_id = ?
                    """,
                    (
                        row["to_room_id"],
                        row["return_exit_name"],
                        row["from_room_id"],
                    ),
                )

            clean_return_name = None
            if bidirectional:
                clean_return_name = self._clean_name(
                    return_exit_name or row["exit_name"], "Return exit name"
                )
                conflict = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND (
                        name = ? COLLATE NOCASE OR destination_room_id = ?
                    )
                    """,
                    (
                        row["to_room_id"],
                        clean_return_name,
                        row["from_room_id"],
                    ),
                ).fetchone()
                if conflict is not None:
                    raise InvalidMovementError(
                        "That return connection conflicts with an existing exit."
                    )
                connection.execute(
                    """
                    INSERT INTO room_exits (room_id, name, destination_room_id)
                    VALUES (?, ?, ?)
                    """,
                    (
                        row["to_room_id"],
                        clean_return_name,
                        row["from_room_id"],
                    ),
                )

            connection.execute(
                """
                UPDATE room_connections
                SET return_exit_name = ?, bidirectional = ?
                WHERE id = ?
                """,
                (clean_return_name, int(bidirectional), row["id"]),
            )

    def disconnect_connection(self, room_id: str, exit_name: str) -> None:
        """Remove a canonical connection and both exits when applicable."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, exit_name,
                       return_exit_name, bidirectional
                FROM room_connections
                WHERE from_room_id = ? AND exit_name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )
            connection.execute(
                """
                DELETE FROM room_exits
                WHERE room_id = ? AND name = ? COLLATE NOCASE
                  AND destination_room_id = ?
                """,
                (row["from_room_id"], row["exit_name"], row["to_room_id"]),
            )
            if row["bidirectional"] and row["return_exit_name"]:
                connection.execute(
                    """
                    DELETE FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                      AND destination_room_id = ?
                    """,
                    (
                        row["to_room_id"],
                        row["return_exit_name"],
                        row["from_room_id"],
                    ),
                )
            connection.execute(
                "DELETE FROM character_known_connections WHERE connection_id = ?",
                (row["id"],),
            )
            connection.execute(
                "DELETE FROM room_connections WHERE id = ?", (row["id"],)
            )
