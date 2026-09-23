"""Dungeon, area, and floor persistence for the database facade."""

from __future__ import annotations

import sqlite3

from ..world.dungeon import Dungeon, Floor
from ..world import Area, NotFoundError


class DatabaseDungeonsMixin:
    """Persist top-level dungeons, areas, and floors."""

    def create_area(
        self, area_id: str, name: str, description: str | None = None
    ) -> Area:
        area_id = self._clean_identifier(area_id, "Area ID")
        name = self._clean_name(name, "Area name")
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO areas (id, name, description) VALUES (?, ?, ?)",
                    (area_id, name, description),
                )
                connection.execute(
                    """
                    INSERT INTO dungeon_floors (id, dungeon_id, floor_number, name)
                    VALUES (?, ?, 1, 'Floor 1')
                    """,
                    (f"{area_id}:floor:1", area_id),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Area '{area_id}' already exists.") from error
        area = self.get_area(area_id)
        assert area is not None
        return area

    def get_area(self, area_id: str) -> Area | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, name, description FROM areas WHERE id = ?", (area_id,)
            ).fetchone()
            if row is None:
                return None
            room_ids = tuple(
                item["id"]
                for item in connection.execute(
                    "SELECT id FROM rooms WHERE area_id = ? ORDER BY id", (area_id,)
                )
            )
            return Area(row["id"], row["name"], row["description"], room_ids)

    def list_areas(self) -> tuple[Area, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, description FROM areas ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
            return tuple(
                Area(
                    row["id"],
                    row["name"],
                    row["description"],
                    tuple(
                        room["id"]
                        for room in connection.execute(
                            "SELECT id FROM rooms WHERE area_id = ? ORDER BY id",
                            (row["id"],),
                        )
                    ),
                )
                for row in rows
            )

    def create_floor(
        self, floor_id: str, dungeon_id: str, floor_number: int, name: str
    ) -> Floor:
        floor_id = self._clean_identifier(floor_id, "Floor ID")
        name = self._clean_name(name, "Floor name")
        if isinstance(floor_number, bool) or not isinstance(floor_number, int):
            raise ValueError("Floor number must be an integer.")
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM areas WHERE id = ?", (dungeon_id,)
            ).fetchone() is None:
                raise NotFoundError(f"Dungeon '{dungeon_id}' does not exist.")
            try:
                connection.execute(
                    """
                    INSERT INTO dungeon_floors (id, dungeon_id, floor_number, name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (floor_id, dungeon_id, floor_number, name),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("That floor ID or floor number already exists.") from error
        return Floor(floor_id, dungeon_id, floor_number, name)

    def get_floor(self, floor_id: str) -> Floor | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, dungeon_id, floor_number, name
                FROM dungeon_floors WHERE id = ?
                """,
                (floor_id,),
            ).fetchone()
        return (
            Floor(row["id"], row["dungeon_id"], row["floor_number"], row["name"])
            if row else None
        )

    def list_floors(self, dungeon_id: str) -> tuple[Floor, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, dungeon_id, floor_number, name FROM dungeon_floors
                WHERE dungeon_id = ? ORDER BY floor_number, id
                """,
                (dungeon_id,),
            ).fetchall()
        return tuple(
            Floor(row["id"], row["dungeon_id"], row["floor_number"], row["name"])
            for row in rows
        )

    def get_dungeon(self, dungeon_id: str) -> Dungeon | None:
        area = self.get_area(dungeon_id)
        if area is None:
            return None
        return Dungeon(area.id, area.name, self.list_floors(area.id))

    def list_dungeons(self) -> tuple[Dungeon, ...]:
        return tuple(
            Dungeon(area.id, area.name, self.list_floors(area.id))
            for area in self.list_areas()
        )
