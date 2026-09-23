"""SQLite persistence dedicated to combat scene state."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .models import (
    CombatLandmark,
    CombatLogEntry,
    CombatRoute,
    CombatScene,
    CombatStatus,
    CombatantKind,
    CombatantState,
    LandmarkDistance,
    LandmarkRelation,
)


class CombatRepository:
    """Persist combat state without growing the already-large world Database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS combat_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                room_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
                created_at TEXT NOT NULL,
                ended_at TEXT,
                round_number INTEGER NOT NULL DEFAULT 1 CHECK (round_number >= 1),
                current_turn_kind TEXT CHECK (
                    current_turn_kind IS NULL
                    OR current_turn_kind IN ('character', 'enemy')
                ),
                current_turn_source_id TEXT,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS one_active_combat_per_guild
            ON combat_scenes(guild_id)
            WHERE status = 'active';

            CREATE TABLE IF NOT EXISTS combat_landmarks (
                scene_id INTEGER NOT NULL,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                source_feature_id TEXT,
                source_connection_id TEXT,
                feature_type TEXT,
                synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0, 1)),
                x REAL,
                y REAL,
                PRIMARY KEY (scene_id, id),
                FOREIGN KEY (scene_id) REFERENCES combat_scenes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS combat_routes (
                scene_id INTEGER NOT NULL,
                source_landmark_id TEXT NOT NULL,
                destination_landmark_id TEXT NOT NULL,
                distance TEXT NOT NULL CHECK (distance IN ('close', 'far', 'distant')),
                obstacle TEXT,
                blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1)),
                PRIMARY KEY (scene_id, source_landmark_id, destination_landmark_id),
                FOREIGN KEY (scene_id) REFERENCES combat_scenes(id) ON DELETE CASCADE,
                FOREIGN KEY (scene_id, source_landmark_id)
                    REFERENCES combat_landmarks(scene_id, id) ON DELETE CASCADE,
                FOREIGN KEY (scene_id, destination_landmark_id)
                    REFERENCES combat_landmarks(scene_id, id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS combatants (
                scene_id INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('character', 'enemy')),
                source_id TEXT NOT NULL,
                name TEXT NOT NULL,
                landmark_id TEXT NOT NULL,
                relation TEXT NOT NULL CHECK (
                    relation IN ('at', 'beside', 'behind', 'on', 'inside')
                ),
                initiative_roll INTEGER NOT NULL DEFAULT 0,
                initiative_score INTEGER NOT NULL DEFAULT 0,
                acted_this_round INTEGER NOT NULL DEFAULT 0 CHECK (acted_this_round IN (0, 1)),
                movement_budget INTEGER NOT NULL DEFAULT 3 CHECK (movement_budget >= 1),
                movement_remaining INTEGER NOT NULL DEFAULT 3 CHECK (movement_remaining >= 0),
                route_source_landmark_id TEXT,
                route_destination_landmark_id TEXT,
                route_progress INTEGER NOT NULL DEFAULT 0 CHECK (route_progress >= 0),
                route_cost INTEGER NOT NULL DEFAULT 0 CHECK (route_cost >= 0),
                standard_action_spent INTEGER NOT NULL DEFAULT 0
                    CHECK (standard_action_spent IN (0, 1)),
                PRIMARY KEY (scene_id, kind, source_id),
                FOREIGN KEY (scene_id) REFERENCES combat_scenes(id) ON DELETE CASCADE,
                FOREIGN KEY (scene_id, landmark_id)
                    REFERENCES combat_landmarks(scene_id, id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS combat_log_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scene_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL CHECK (round_number >= 1),
                event_type TEXT NOT NULL,
                actor_kind TEXT CHECK (
                    actor_kind IS NULL OR actor_kind IN ('character', 'enemy')
                ),
                actor_source_id TEXT,
                actor_name TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (scene_id) REFERENCES combat_scenes(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS combat_log_by_scene
                ON combat_log_entries(scene_id, id);
            """
        )
        landmark_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(combat_landmarks)")
        }
        if "source_connection_id" not in landmark_columns:
            connection.execute(
                "ALTER TABLE combat_landmarks ADD COLUMN source_connection_id TEXT"
            )

        scene_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(combat_scenes)")
        }
        if "round_number" not in scene_columns:
            connection.execute(
                "ALTER TABLE combat_scenes ADD COLUMN round_number INTEGER NOT NULL DEFAULT 1"
            )
        if "current_turn_kind" not in scene_columns:
            connection.execute(
                "ALTER TABLE combat_scenes ADD COLUMN current_turn_kind TEXT"
            )
        if "current_turn_source_id" not in scene_columns:
            connection.execute(
                "ALTER TABLE combat_scenes ADD COLUMN current_turn_source_id TEXT"
            )

        combatant_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(combatants)")
        }
        if "initiative_roll" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN initiative_roll INTEGER NOT NULL DEFAULT 0"
            )
        if "initiative_score" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN initiative_score INTEGER NOT NULL DEFAULT 0"
            )
        if "acted_this_round" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN acted_this_round INTEGER NOT NULL DEFAULT 0"
            )
        if "movement_budget" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN movement_budget INTEGER NOT NULL DEFAULT 3"
            )
        if "movement_remaining" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN movement_remaining INTEGER NOT NULL DEFAULT 3"
            )
        if "route_source_landmark_id" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN route_source_landmark_id TEXT"
            )
        if "route_destination_landmark_id" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN route_destination_landmark_id TEXT"
            )
        if "route_progress" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN route_progress INTEGER NOT NULL DEFAULT 0"
            )
        if "route_cost" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN route_cost INTEGER NOT NULL DEFAULT 0"
            )
        if "standard_action_spent" not in combatant_columns:
            connection.execute(
                "ALTER TABLE combatants ADD COLUMN standard_action_spent INTEGER NOT NULL DEFAULT 0"
            )

    def start_scene(
        self,
        guild_id: int,
        room_id: str,
        landmarks: tuple[CombatLandmark, ...],
        combatants: tuple[CombatantState, ...],
    ) -> CombatScene:
        if guild_id <= 0:
            raise ValueError("Guild ID must be a positive Discord ID.")
        if not landmarks:
            raise ValueError("A combat scene needs at least one landmark.")

        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                """
                SELECT 1 FROM combat_scenes
                WHERE guild_id = ? AND status = 'active'
                """,
                (guild_id,),
            ).fetchone() is not None:
                raise ValueError("This server already has an active combat scene.")
            if connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?",
                (room_id,),
            ).fetchone() is None:
                raise ValueError(f"Room '{room_id}' does not exist.")

            now = datetime.now(timezone.utc).isoformat()
            cursor = connection.execute(
                """
                INSERT INTO combat_scenes (
                    guild_id, room_id, status, created_at
                ) VALUES (?, ?, 'active', ?)
                """,
                (guild_id, room_id, now),
            )
            scene_id = int(cursor.lastrowid)

            connection.executemany(
                """
                INSERT INTO combat_landmarks (
                    scene_id, id, name, description, source_feature_id,
                    source_connection_id, feature_type, synthetic, x, y
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        scene_id,
                        landmark.id,
                        landmark.name,
                        landmark.description,
                        landmark.source_feature_id,
                        landmark.source_connection_id,
                        landmark.feature_type,
                        int(landmark.synthetic),
                        landmark.x,
                        landmark.y,
                    )
                    for landmark in landmarks
                ],
            )

            landmark_ids = {landmark.id for landmark in landmarks}
            for combatant in combatants:
                if combatant.landmark_id not in landmark_ids:
                    raise ValueError(
                        f"Unknown starting landmark '{combatant.landmark_id}'."
                    )
            connection.executemany(
                """
                INSERT INTO combatants (
                    scene_id, kind, source_id, name, landmark_id, relation,
                    initiative_roll, initiative_score, acted_this_round,
                    movement_budget, movement_remaining,
                    route_source_landmark_id, route_destination_landmark_id,
                    route_progress, route_cost, standard_action_spent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        scene_id,
                        combatant.kind.value,
                        combatant.source_id,
                        combatant.name,
                        combatant.landmark_id,
                        combatant.relation.value,
                        combatant.initiative_roll,
                        combatant.initiative_score,
                        int(combatant.acted_this_round),
                        combatant.movement_budget,
                        combatant.movement_remaining,
                        combatant.route_source_landmark_id,
                        combatant.route_destination_landmark_id,
                        combatant.route_progress,
                        combatant.route_cost,
                        int(combatant.standard_action_spent),
                    )
                    for combatant in combatants
                ],
            )

            if combatants:
                first = min(
                    combatants,
                    key=lambda combatant: combatant.initiative_key,
                )
                connection.execute(
                    """
                    UPDATE combat_scenes
                    SET current_turn_kind = ?, current_turn_source_id = ?
                    WHERE id = ?
                    """,
                    (first.kind.value, first.source_id, scene_id),
                )

            row = connection.execute(
                """
                SELECT id, guild_id, room_id, status, round_number,
                       current_turn_kind, current_turn_source_id
                FROM combat_scenes WHERE id = ?
                """,
                (scene_id,),
            ).fetchone()
            assert row is not None
            return self._load_scene(connection, row)

    def get_active_scene(self, guild_id: int) -> CombatScene | None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, guild_id, room_id, status, round_number,
                       current_turn_kind, current_turn_source_id
                FROM combat_scenes
                WHERE guild_id = ? AND status = 'active'
                """,
                (guild_id,),
            ).fetchone()
            return self._load_scene(connection, row) if row is not None else None

    def add_combatant(
        self,
        scene_id: int,
        combatant: CombatantState,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                "SELECT 1 FROM combat_scenes WHERE id = ? AND status = 'active'",
                (scene_id,),
            ).fetchone() is None:
                raise ValueError("The combat scene is not active.")
            if connection.execute(
                """
                SELECT 1 FROM combat_landmarks
                WHERE scene_id = ? AND id = ?
                """,
                (scene_id, combatant.landmark_id),
            ).fetchone() is None:
                raise ValueError(
                    f"Unknown combat landmark '{combatant.landmark_id}'."
                )
            try:
                connection.execute(
                    """
                    INSERT INTO combatants (
                        scene_id, kind, source_id, name, landmark_id, relation,
                        initiative_roll, initiative_score, acted_this_round,
                        movement_budget, movement_remaining,
                        route_source_landmark_id, route_destination_landmark_id,
                        route_progress, route_cost, standard_action_spent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scene_id,
                        combatant.kind.value,
                        combatant.source_id,
                        combatant.name,
                        combatant.landmark_id,
                        combatant.relation.value,
                        combatant.initiative_roll,
                        combatant.initiative_score,
                        int(combatant.acted_this_round),
                        combatant.movement_budget,
                        combatant.movement_remaining,
                        combatant.route_source_landmark_id,
                        combatant.route_destination_landmark_id,
                        combatant.route_progress,
                        combatant.route_cost,
                        int(combatant.standard_action_spent),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Combatant '{combatant.kind.value}:{combatant.source_id}' "
                    "is already in this scene."
                ) from error

    def remove_combatant(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                DELETE FROM combatants
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    def set_turn(
        self,
        scene_id: int,
        round_number: int,
        kind: CombatantKind | None,
        source_id: str | None,
    ) -> None:
        if round_number < 1:
            raise ValueError("Combat round must be at least 1.")
        if (kind is None) != (source_id is None):
            raise ValueError(
                "Combat turn kind and source ID must both be set or both be empty."
            )

        with self._connect() as connection:
            self._ensure_schema(connection)
            if kind is not None and source_id is not None:
                if connection.execute(
                    """
                    SELECT 1 FROM combatants
                    WHERE scene_id = ? AND kind = ? AND source_id = ?
                    """,
                    (scene_id, kind.value, source_id),
                ).fetchone() is None:
                    raise ValueError(
                        f"Unknown combatant '{kind.value}:{source_id}'."
                    )
            cursor = connection.execute(
                """
                UPDATE combat_scenes
                SET round_number = ?,
                    current_turn_kind = ?,
                    current_turn_source_id = ?
                WHERE id = ? AND status = 'active'
                """,
                (
                    round_number,
                    kind.value if kind is not None else None,
                    source_id,
                    scene_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("The combat scene is not active.")

    def set_initiative(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
        initiative_score: int,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combatants
                SET initiative_score = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (initiative_score, scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    def set_combatant_acted(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
        acted: bool,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combatants
                SET acted_this_round = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (int(acted), scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    def set_standard_action_spent(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
        spent: bool,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combatants
                SET standard_action_spent = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (int(spent), scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    def reset_standard_action(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
    ) -> None:
        self.set_standard_action_spent(
            scene_id,
            kind,
            source_id,
            False,
        )

    def set_all_combatants_acted(
        self,
        scene_id: int,
        acted: bool,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            connection.execute(
                """
                UPDATE combatants
                SET acted_this_round = ?
                WHERE scene_id = ?
                """,
                (int(acted), scene_id),
            )

    def append_log(
        self,
        scene_id: int,
        round_number: int,
        event_type: str,
        message: str,
        *,
        actor_kind: CombatantKind | None = None,
        actor_source_id: str | None = None,
        actor_name: str | None = None,
    ) -> None:
        event_type = event_type.strip()
        message = message.strip()
        if not event_type:
            raise ValueError("Combat log event type is required.")
        if not message:
            raise ValueError("Combat log message is required.")
        if round_number < 1:
            raise ValueError("Combat log round must be at least 1.")

        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                "SELECT 1 FROM combat_scenes WHERE id = ?",
                (scene_id,),
            ).fetchone() is None:
                raise ValueError("Combat scene does not exist.")
            connection.execute(
                """
                INSERT INTO combat_log_entries (
                    scene_id, round_number, event_type,
                    actor_kind, actor_source_id, actor_name,
                    message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scene_id,
                    round_number,
                    event_type,
                    actor_kind.value if actor_kind is not None else None,
                    actor_source_id,
                    actor_name,
                    message,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def end_scene(self, guild_id: int) -> CombatScene | None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, guild_id, room_id, status, round_number,
                       current_turn_kind, current_turn_source_id
                FROM combat_scenes
                WHERE guild_id = ? AND status = 'active'
                """,
                (guild_id,),
            ).fetchone()
            if row is None:
                return None
            scene_id = int(row["id"])
            connection.execute(
                """
                UPDATE combat_scenes
                SET status = 'ended', ended_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), scene_id),
            )
            ended = connection.execute(
                """
                SELECT id, guild_id, room_id, status, round_number,
                       current_turn_kind, current_turn_source_id
                FROM combat_scenes WHERE id = ?
                """,
                (scene_id,),
            ).fetchone()
            assert ended is not None
            return self._load_scene(connection, ended)

    def add_landmark(
        self,
        scene_id: int,
        landmark: CombatLandmark,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                "SELECT 1 FROM combat_scenes WHERE id = ? AND status = 'active'",
                (scene_id,),
            ).fetchone() is None:
                raise ValueError("The combat scene is not active.")
            try:
                connection.execute(
                    """
                    INSERT INTO combat_landmarks (
                        scene_id, id, name, description, source_feature_id,
                        source_connection_id, feature_type, synthetic, x, y
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scene_id,
                        landmark.id,
                        landmark.name,
                        landmark.description,
                        landmark.source_feature_id,
                        landmark.source_connection_id,
                        landmark.feature_type,
                        int(landmark.synthetic),
                        landmark.x,
                        landmark.y,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Combat landmark '{landmark.id}' already exists."
                ) from error

    def delete_landmark(
        self,
        scene_id: int,
        landmark_id: str,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                DELETE FROM combat_landmarks
                WHERE scene_id = ? AND id = ?
                """,
                (scene_id, landmark_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown combat landmark '{landmark_id}'.")

    def set_landmark_position(
        self,
        scene_id: int,
        landmark_id: str,
        x: float,
        y: float,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combat_landmarks
                SET x = ?, y = ?
                WHERE scene_id = ? AND id = ?
                """,
                (x, y, scene_id, landmark_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown combat landmark '{landmark_id}'.")

    def set_route(
        self,
        scene_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
        distance: LandmarkDistance,
        *,
        obstacle: str | None = None,
        blocked: bool = False,
    ) -> None:
        if source_landmark_id == destination_landmark_id:
            raise ValueError("A combat route needs two different landmarks.")
        source_landmark_id, destination_landmark_id = sorted(
            (source_landmark_id, destination_landmark_id)
        )
        with self._connect() as connection:
            self._ensure_schema(connection)
            for landmark_id in (source_landmark_id, destination_landmark_id):
                if connection.execute(
                    """
                    SELECT 1 FROM combat_landmarks
                    WHERE scene_id = ? AND id = ?
                    """,
                    (scene_id, landmark_id),
                ).fetchone() is None:
                    raise ValueError(f"Unknown combat landmark '{landmark_id}'.")
            connection.execute(
                """
                INSERT INTO combat_routes (
                    scene_id, source_landmark_id, destination_landmark_id,
                    distance, obstacle, blocked
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scene_id, source_landmark_id, destination_landmark_id)
                DO UPDATE SET
                    distance = excluded.distance,
                    obstacle = excluded.obstacle,
                    blocked = excluded.blocked
                """,
                (
                    scene_id,
                    source_landmark_id,
                    destination_landmark_id,
                    distance.value,
                    obstacle,
                    int(blocked),
                ),
            )

    def delete_route(
        self,
        scene_id: int,
        source_landmark_id: str,
        destination_landmark_id: str,
    ) -> None:
        source_landmark_id, destination_landmark_id = sorted(
            (source_landmark_id, destination_landmark_id)
        )
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                DELETE FROM combat_routes
                WHERE scene_id = ?
                  AND source_landmark_id = ?
                  AND destination_landmark_id = ?
                """,
                (
                    scene_id,
                    source_landmark_id,
                    destination_landmark_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError("That combat connection does not exist.")

    def set_combatant_position(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
        landmark_id: str,
        relation: LandmarkRelation,
        *,
        movement_remaining: int | None = None,
        route_source_landmark_id: str | None = None,
        route_destination_landmark_id: str | None = None,
        route_progress: int = 0,
        route_cost: int = 0,
    ) -> None:
        if movement_remaining is not None and movement_remaining < 0:
            raise ValueError("Movement remaining cannot be negative.")
        if route_progress < 0 or route_cost < 0 or route_progress > route_cost:
            raise ValueError("Combat route progress is invalid.")
        route_values = (
            route_source_landmark_id,
            route_destination_landmark_id,
        )
        if (route_source_landmark_id is None) != (
            route_destination_landmark_id is None
        ):
            raise ValueError(
                "Both route endpoints are required for partial movement."
            )
        if route_source_landmark_id is None and (route_progress or route_cost):
            raise ValueError("Route progress requires route endpoints.")

        with self._connect() as connection:
            self._ensure_schema(connection)
            landmark_ids = {landmark_id}
            landmark_ids.update(
                value for value in route_values if value is not None
            )
            for candidate_id in landmark_ids:
                if connection.execute(
                    """
                    SELECT 1 FROM combat_landmarks
                    WHERE scene_id = ? AND id = ?
                    """,
                    (scene_id, candidate_id),
                ).fetchone() is None:
                    raise ValueError(
                        f"Unknown combat landmark '{candidate_id}'."
                    )

            cursor = connection.execute(
                """
                UPDATE combatants
                SET landmark_id = ?,
                    relation = ?,
                    movement_remaining = COALESCE(?, movement_remaining),
                    route_source_landmark_id = ?,
                    route_destination_landmark_id = ?,
                    route_progress = ?,
                    route_cost = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (
                    landmark_id,
                    relation.value,
                    movement_remaining,
                    route_source_landmark_id,
                    route_destination_landmark_id,
                    route_progress,
                    route_cost,
                    scene_id,
                    kind.value,
                    source_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown combatant '{kind.value}:{source_id}'.")

    def reset_combatant_movement(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combatants
                SET movement_remaining = movement_budget
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    def set_movement_remaining(
        self,
        scene_id: int,
        kind: CombatantKind,
        source_id: str,
        remaining: int,
    ) -> None:
        if remaining < 0:
            raise ValueError("Movement remaining cannot be negative.")
        with self._connect() as connection:
            self._ensure_schema(connection)
            cursor = connection.execute(
                """
                UPDATE combatants
                SET movement_remaining = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (remaining, scene_id, kind.value, source_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Unknown combatant '{kind.value}:{source_id}'."
                )

    @staticmethod
    def _load_scene(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> CombatScene:
        scene_id = int(row["id"])
        landmark_rows = connection.execute(
            """
            SELECT id, name, description, source_feature_id, source_connection_id,
                   feature_type, synthetic, x, y
            FROM combat_landmarks
            WHERE scene_id = ?
            ORDER BY synthetic DESC, name COLLATE NOCASE, id
            """,
            (scene_id,),
        ).fetchall()
        route_rows = connection.execute(
            """
            SELECT source_landmark_id, destination_landmark_id,
                   distance, obstacle, blocked
            FROM combat_routes
            WHERE scene_id = ?
            ORDER BY source_landmark_id, destination_landmark_id
            """,
            (scene_id,),
        ).fetchall()
        combatant_rows = connection.execute(
            """
            SELECT kind, source_id, name, landmark_id, relation,
                   initiative_roll, initiative_score, acted_this_round,
                   movement_budget, movement_remaining,
                   route_source_landmark_id, route_destination_landmark_id,
                   route_progress, route_cost, standard_action_spent
            FROM combatants
            WHERE scene_id = ?
            ORDER BY initiative_score DESC, initiative_roll DESC,
                     kind, name COLLATE NOCASE, source_id
            """,
            (scene_id,),
        ).fetchall()
        log_rows = connection.execute(
            """
            SELECT id, round_number, event_type, actor_kind,
                   actor_source_id, actor_name, message, created_at
            FROM combat_log_entries
            WHERE scene_id = ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (scene_id,),
        ).fetchall()
        return CombatScene(
            scene_id,
            int(row["guild_id"]),
            row["room_id"],
            CombatStatus(row["status"]),
            tuple(
                CombatLandmark(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    source_feature_id=item["source_feature_id"],
                    source_connection_id=item["source_connection_id"],
                    feature_type=item["feature_type"],
                    synthetic=bool(item["synthetic"]),
                    x=item["x"],
                    y=item["y"],
                )
                for item in landmark_rows
            ),
            tuple(
                CombatRoute(
                    item["source_landmark_id"],
                    item["destination_landmark_id"],
                    LandmarkDistance(item["distance"]),
                    item["obstacle"],
                    bool(item["blocked"]),
                )
                for item in route_rows
            ),
            tuple(
                CombatantState(
                    CombatantKind(item["kind"]),
                    item["source_id"],
                    item["name"],
                    item["landmark_id"],
                    LandmarkRelation(item["relation"]),
                    item["initiative_roll"],
                    item["initiative_score"],
                    bool(item["acted_this_round"]),
                    item["movement_budget"],
                    item["movement_remaining"],
                    item["route_source_landmark_id"],
                    item["route_destination_landmark_id"],
                    item["route_progress"],
                    item["route_cost"],
                    bool(item["standard_action_spent"]),
                )
                for item in combatant_rows
            ),
            int(row["round_number"]),
            (
                CombatantKind(row["current_turn_kind"])
                if row["current_turn_kind"] is not None
                else None
            ),
            row["current_turn_source_id"],
            tuple(
                CombatLogEntry(
                    id=item["id"],
                    round_number=item["round_number"],
                    event_type=item["event_type"],
                    message=item["message"],
                    created_at=item["created_at"],
                    actor_kind=(
                        CombatantKind(item["actor_kind"])
                        if item["actor_kind"] is not None
                        else None
                    ),
                    actor_source_id=item["actor_source_id"],
                    actor_name=item["actor_name"],
                )
                for item in reversed(log_rows)
            ),
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
