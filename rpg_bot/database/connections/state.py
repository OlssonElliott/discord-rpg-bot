"""Connection state persistence for the database facade."""

from __future__ import annotations

from ...world.dungeon import ConnectionType
from ...world import NotFoundError


class DatabaseConnectionStateMixin:
    """Persist connection type, lock state, and open state."""

    def set_connection_type(
        self,
        room_id: str,
        exit_name: str,
        connection_type: ConnectionType,
    ) -> None:
        """Change how a canonical connection is represented on player maps."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, bidirectional
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
                "UPDATE room_connections SET connection_type = ? WHERE id = ?",
                (connection_type.value, row["id"]),
            )
            if connection_type is not ConnectionType.DOOR:
                connection.execute(
                    """
                    UPDATE room_connections
                    SET has_lock = 0, is_locked = 0, is_broken = 0,
                        is_open = 0, unlock_difficulty = NULL
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
            if connection_type not in (
                ConnectionType.DOOR,
                ConnectionType.HALLWAY,
                ConnectionType.PASSAGE,
            ):
                connection.execute(
                    """
                    UPDATE room_connections
                    SET has_trap = 0, trap_state = NULL,
                        trap_detection_difficulty = NULL,
                        trap_damage_type = NULL, trap_damage = NULL
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
            if connection_type is not ConnectionType.DOOR:
                present = connection.execute(
                    """
                    SELECT id, current_room_id
                    FROM characters
                    WHERE is_archived = 0 AND (
                        current_room_id = ?
                        OR (current_room_id = ? AND ? = 1)
                    )
                    """,
                    (
                        row["from_room_id"],
                        row["to_room_id"],
                        row["bidirectional"],
                    ),
                ).fetchall()
                for character in present:
                    self._record_visible_connections(
                        connection, character["id"], character["current_room_id"]
                    )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    def set_connection_lock(
        self,
        room_id: str,
        exit_name: str,
        *,
        has_lock: bool,
        is_locked: bool,
        is_broken: bool = False,
        unlock_difficulty: int | None = None,
    ) -> None:
        """Set the lock state and unlock difficulty for a door connection."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, connection_type
                FROM room_connections
                WHERE (
                    from_room_id = ? AND exit_name = ? COLLATE NOCASE
                ) OR (
                    to_room_id = ? AND bidirectional = 1
                    AND return_exit_name = ? COLLATE NOCASE
                )
                """,
                (room_id, exit_name, room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )
            difficulty = self._validate_connection_lock(
                ConnectionType(row["connection_type"]),
                has_lock,
                is_locked,
                is_broken,
                unlock_difficulty,
            )
            connection.execute(
                """
                UPDATE room_connections
                SET has_lock = ?, is_locked = ?, is_broken = ?,
                    unlock_difficulty = ?,
                    is_open = CASE WHEN ? = 1 THEN 0 ELSE is_open END
                WHERE id = ?
                """,
                (
                    int(has_lock), int(is_locked), int(is_broken),
                    difficulty, int(is_locked), row["id"],
                ),
            )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    def set_connection_open(
        self,
        room_id: str,
        exit_name: str,
        *,
        is_open: bool,
    ) -> None:
        """Open or close a door, revealing its far room only while observed."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, bidirectional,
                       connection_type, is_locked
                FROM room_connections
                WHERE (
                    from_room_id = ? AND exit_name = ? COLLATE NOCASE
                ) OR (
                    to_room_id = ? AND bidirectional = 1
                    AND return_exit_name = ? COLLATE NOCASE
                )
                """,
                (room_id, exit_name, room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )
            self._validate_connection_open(
                ConnectionType(row["connection_type"]),
                is_open,
                bool(row["is_locked"]),
            )
            connection.execute(
                "UPDATE room_connections SET is_open = ? WHERE id = ?",
                (int(is_open), row["id"]),
            )
            if is_open:
                present = connection.execute(
                    """
                    SELECT id, current_room_id
                    FROM characters
                    WHERE is_archived = 0 AND (
                        current_room_id = ?
                        OR (current_room_id = ? AND ? = 1)
                    )
                    """,
                    (
                        row["from_room_id"],
                        row["to_room_id"],
                        row["bidirectional"],
                    ),
                ).fetchall()
                for character in present:
                    self._record_visible_connections(
                        connection, character["id"], character["current_room_id"]
                    )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    @staticmethod
    def _validate_connection_lock(
        connection_type: ConnectionType,
        has_lock: bool,
        is_locked: bool,
        is_broken: bool,
        unlock_difficulty: int | None,
    ) -> int | None:
        if has_lock and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can have a lock.")
        from ...world.locks import validate_lock

        return validate_lock(
            has_lock,
            is_locked,
            is_broken,
            unlock_difficulty,
            subject="door",
        )

    @staticmethod
    def _validate_connection_open(
        connection_type: ConnectionType,
        is_open: bool,
        is_locked: bool,
    ) -> None:
        if is_open and connection_type is not ConnectionType.DOOR:
            raise ValueError("Only door connections can be open.")
        if is_open and is_locked:
            raise ValueError("A locked door cannot be open.")
