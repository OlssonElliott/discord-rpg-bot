"""SQLite persistence dedicated to combat scene state."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from .combat import (
    CombatLandmark,
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
                PRIMARY KEY (scene_id, kind, source_id),
                FOREIGN KEY (scene_id) REFERENCES combat_scenes(id) ON DELETE CASCADE,
                FOREIGN KEY (scene_id, landmark_id)
                    REFERENCES combat_landmarks(scene_id, id) ON DELETE RESTRICT
            );
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
                    scene_id, kind, source_id, name, landmark_id, relation
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        scene_id,
                        combatant.kind.value,
                        combatant.source_id,
                        combatant.name,
                        combatant.landmark_id,
                        combatant.relation.value,
                    )
                    for combatant in combatants
                ],
            )

            row = connection.execute(
                """
                SELECT id, guild_id, room_id, status
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
                SELECT id, guild_id, room_id, status
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
                        scene_id, kind, source_id, name, landmark_id, relation
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        scene_id,
                        combatant.kind.value,
                        combatant.source_id,
                        combatant.name,
                        combatant.landmark_id,
                        combatant.relation.value,
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

    def end_scene(self, guild_id: int) -> CombatScene | None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            row = connection.execute(
                """
                SELECT id, guild_id, room_id, status
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
                SELECT id, guild_id, room_id, status
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
    ) -> None:
        with self._connect() as connection:
            self._ensure_schema(connection)
            if connection.execute(
                """
                SELECT 1 FROM combat_landmarks
                WHERE scene_id = ? AND id = ?
                """,
                (scene_id, landmark_id),
            ).fetchone() is None:
                raise ValueError(f"Unknown combat landmark '{landmark_id}'.")
            cursor = connection.execute(
                """
                UPDATE combatants
                SET landmark_id = ?, relation = ?
                WHERE scene_id = ? AND kind = ? AND source_id = ?
                """,
                (
                    landmark_id,
                    relation.value,
                    scene_id,
                    kind.value,
                    source_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown combatant '{kind.value}:{source_id}'.")

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
            SELECT kind, source_id, name, landmark_id, relation
            FROM combatants
            WHERE scene_id = ?
            ORDER BY kind, name COLLATE NOCASE, source_id
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
                )
                for item in combatant_rows
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
