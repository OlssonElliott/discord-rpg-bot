"""Room feature persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ...world import NotFoundError


class DatabaseRoomFeaturesMixin:
    """Persist room features and reusable room-feature templates."""

    @staticmethod
    def _ensure_room_features_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS room_features (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                feature_type TEXT NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS room_features_by_room
            ON room_features(room_id)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS room_feature_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                feature_type TEXT NOT NULL
            )
            """
        )

    def create_room_feature(
        self,
        feature_id: str,
        room_id: str,
        name: str,
        feature_type,
        description: str | None = None,
    ):
        from ...world.room_features import RoomFeature

        clean_id = self._clean_identifier(feature_id, "Room feature ID")
        clean_name = self._clean_name(name, "Room feature name")
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO room_features (
                        id, room_id, name, description, feature_type
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        room_id,
                        clean_name,
                        description,
                        feature_type.value,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Room feature '{clean_id}' already exists."
                ) from error
        return RoomFeature(
            clean_id,
            room_id,
            clean_name,
            feature_type,
            description,
        )

    def get_room_feature(self, feature_id: str):
        from ...world.room_features import RoomFeature, RoomFeatureType

        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            row = connection.execute(
                """
                SELECT id, room_id, name, description, feature_type
                FROM room_features
                WHERE id = ?
                """,
                (feature_id,),
            ).fetchone()
        if row is None:
            return None
        return RoomFeature(
            row["id"],
            row["room_id"],
            row["name"],
            RoomFeatureType(row["feature_type"]),
            row["description"],
        )

    def list_room_features(self, room_id: str):
        from ...world.room_features import RoomFeature, RoomFeatureType

        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            self._require_room(connection, room_id)
            rows = connection.execute(
                """
                SELECT id, room_id, name, description, feature_type
                FROM room_features
                WHERE room_id = ?
                ORDER BY name COLLATE NOCASE, id
                """,
                (room_id,),
            ).fetchall()
        return tuple(
            RoomFeature(
                row["id"],
                row["room_id"],
                row["name"],
                RoomFeatureType(row["feature_type"]),
                row["description"],
            )
            for row in rows
        )

    def update_room_feature(self, feature):
        clean_name = self._clean_name(feature.name, "Room feature name")
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            cursor = connection.execute(
                """
                UPDATE room_features
                SET name = ?, description = ?, feature_type = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    feature.description,
                    feature.feature_type.value,
                    feature.id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Room feature '{feature.id}' does not exist."
                )
        updated = self.get_room_feature(feature.id)
        assert updated is not None
        return updated

    def remove_room_feature(self, feature_id: str) -> None:
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            cursor = connection.execute(
                "DELETE FROM room_features WHERE id = ?",
                (feature_id,),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Room feature '{feature_id}' does not exist."
                )

    def create_room_feature_template(
        self,
        template_id: str,
        name: str,
        feature_type,
        description: str | None = None,
    ):
        from ...world.room_features import RoomFeatureTemplate

        clean_id = self._clean_identifier(template_id, "Room feature template ID")
        clean_name = self._clean_name(name, "Room feature template name")
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            try:
                connection.execute(
                    """
                    INSERT INTO room_feature_templates (
                        id, name, description, feature_type
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (clean_id, clean_name, description, feature_type.value),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Room feature template '{clean_id}' already exists."
                ) from error
        return RoomFeatureTemplate(
            clean_id,
            clean_name,
            feature_type,
            description,
        )

    def get_room_feature_template(self, template_id: str):
        from ...world.room_features import RoomFeatureTemplate, RoomFeatureType

        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            row = connection.execute(
                """
                SELECT id, name, description, feature_type
                FROM room_feature_templates
                WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return RoomFeatureTemplate(
            row["id"],
            row["name"],
            RoomFeatureType(row["feature_type"]),
            row["description"],
        )

    def list_room_feature_templates(self):
        from ...world.room_features import RoomFeatureTemplate, RoomFeatureType

        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            rows = connection.execute(
                """
                SELECT id, name, description, feature_type
                FROM room_feature_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(
            RoomFeatureTemplate(
                row["id"],
                row["name"],
                RoomFeatureType(row["feature_type"]),
                row["description"],
            )
            for row in rows
        )

    def update_room_feature_template(self, template):
        clean_name = self._clean_name(
            template.name, "Room feature template name"
        )
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            cursor = connection.execute(
                """
                UPDATE room_feature_templates
                SET name = ?, description = ?, feature_type = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    template.description,
                    template.feature_type.value,
                    template.id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Room feature template '{template.id}' does not exist."
                )
        updated = self.get_room_feature_template(template.id)
        assert updated is not None
        return updated

    def remove_room_feature_template(self, template_id: str) -> None:
        with self._connect() as connection:
            self._ensure_room_features_schema(connection)
            cursor = connection.execute(
                "DELETE FROM room_feature_templates WHERE id = ?",
                (template_id,),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Room feature template '{template_id}' does not exist."
                )
