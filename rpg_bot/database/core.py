"""Shared database facade helpers."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import sqlite3

from ..world import NotFoundError


class DatabaseCoreMixin:
    """Provide shared validation, lookup, and connection helpers."""

    @staticmethod
    def _clean_identifier(value: str, label: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError(f"{label} cannot be empty.")
        if len(clean) > 100:
            raise ValueError(f"{label} cannot be longer than 100 characters.")
        return clean

    @staticmethod
    def _clean_name(value: str, label: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError(f"{label} cannot be empty.")
        if len(clean) > 100:
            raise ValueError(f"{label} cannot be longer than 100 characters.")
        return clean

    @staticmethod
    def _require_room(connection: sqlite3.Connection, room_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT id, area_id, name, description, floor_id, width, height,
                   scene_image_path, scene_image_url, scene_prompt
            FROM rooms WHERE id = ?
            """,
            (room_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Room '{room_id}' does not exist.")
        return row

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
