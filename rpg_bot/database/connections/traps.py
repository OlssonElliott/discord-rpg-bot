"""Connection trap persistence for the database facade."""

from __future__ import annotations

from ..errors import CharacterNotFoundError
from ...world.dungeon import ConnectionType, TrapDamageType, TrapState
from ...world import NotFoundError


class DatabaseConnectionTrapsMixin:
    """Persist connection trap configuration and per-character discovery."""

    def get_connection_trap_details(
        self,
        room_id: str,
        exit_name: str,
    ) -> tuple[str, bool, TrapState | None, int | None, int | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, has_trap, trap_state,
                       trap_detection_difficulty, trap_disarm_difficulty
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
        return (
            row["id"],
            bool(row["has_trap"]),
            TrapState(row["trap_state"]) if row["trap_state"] else None,
            row["trap_detection_difficulty"],
            row["trap_disarm_difficulty"],
        )

    def character_knows_trap(
        self,
        character_id: int,
        connection_id: str,
    ) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM character_known_traps
                    WHERE character_id = ? AND connection_id = ?
                    """,
                    (character_id, connection_id),
                ).fetchone()
                is not None
            )

    def mark_trap_detected(
        self,
        character_id: int,
        connection_id: str,
    ) -> None:
        with self._connect() as connection:
            character = connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            connection.execute(
                """
                INSERT OR IGNORE INTO character_known_traps (
                    character_id, connection_id
                ) VALUES (?, ?)
                """,
                (character_id, connection_id),
            )
        self.request_player_map_refresh(character_id)

    def set_connection_trap_state(
        self,
        connection_id: str,
        state: TrapState,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, has_trap
                FROM room_connections
                WHERE id = ?
                """,
                (connection_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"Connection '{connection_id}' does not exist.")
            if not row["has_trap"]:
                raise ValueError("That connection does not have a trap.")
            connection.execute(
                "UPDATE room_connections SET trap_state = ? WHERE id = ?",
                (state.value, connection_id),
            )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    def set_connection_trap_disarm_difficulty(
        self,
        room_id: str,
        exit_name: str,
        difficulty: int | None,
    ) -> None:
        if difficulty is not None and not 1 <= difficulty <= 30:
            raise ValueError(
                "Trap disarm difficulty must be an integer from 1 to 30."
            )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, has_trap
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
            connection.execute(
                """
                UPDATE room_connections
                SET trap_disarm_difficulty = ?
                WHERE id = ?
                """,
                (difficulty if row["has_trap"] else None, row["id"]),
            )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    def set_connection_trap(
        self,
        room_id: str,
        exit_name: str,
        *,
        has_trap: bool,
        trap_state: TrapState | None = None,
        trap_detection_difficulty: int | None = None,
        trap_damage_type: TrapDamageType | None = None,
        trap_damage: int | None = None,
    ) -> None:
        """Configure a trap on a door or hallway connection."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, connection_type
                FROM room_connections
                WHERE from_room_id = ? AND exit_name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )
            state, difficulty, damage_type, damage = self._validate_connection_trap(
                ConnectionType(row["connection_type"]),
                has_trap,
                trap_state,
                trap_detection_difficulty,
                trap_damage_type,
                trap_damage,
            )
            connection.execute(
                """
                UPDATE room_connections
                SET has_trap = ?, trap_state = ?, trap_detection_difficulty = ?,
                    trap_disarm_difficulty = CASE WHEN ? THEN trap_disarm_difficulty ELSE NULL END,
                    trap_damage_type = ?, trap_damage = ?
                WHERE id = ?
                """,
                (
                    int(has_trap),
                    state.value if state is not None else None,
                    difficulty,
                    int(has_trap),
                    damage_type.value if damage_type is not None else None,
                    damage,
                    row["id"],
                ),
            )
            self._queue_map_refresh_for_room(connection, row["from_room_id"])
            self._queue_map_refresh_for_room(connection, row["to_room_id"])

    @staticmethod
    def _validate_connection_trap(
        connection_type: ConnectionType,
        has_trap: bool,
        trap_state: TrapState | None,
        trap_detection_difficulty: int | None,
        trap_damage_type: TrapDamageType | None,
        trap_damage: int | None,
    ) -> tuple[
        TrapState | None,
        int | None,
        TrapDamageType | None,
        int | None,
    ]:
        if not has_trap:
            return None, None, None, None
        if connection_type not in (
            ConnectionType.DOOR,
            ConnectionType.HALLWAY,
            ConnectionType.PASSAGE,
        ):
            raise ValueError("Only door and hallway connections can have a trap.")
        if trap_state is None:
            trap_state = TrapState.ARMED
        if not isinstance(trap_state, TrapState):
            raise ValueError("Trap state is invalid.")
        if (
            isinstance(trap_detection_difficulty, bool)
            or not isinstance(trap_detection_difficulty, int)
            or not 1 <= trap_detection_difficulty <= 30
        ):
            raise ValueError("Trap detection difficulty must be an integer from 1 to 30.")
        if not isinstance(trap_damage_type, TrapDamageType):
            raise ValueError("Trap damage type is invalid.")
        if (
            isinstance(trap_damage, bool)
            or not isinstance(trap_damage, int)
            or trap_damage <= 0
        ):
            raise ValueError("Trap damage must be a positive integer.")
        return trap_state, trap_detection_difficulty, trap_damage_type, trap_damage
