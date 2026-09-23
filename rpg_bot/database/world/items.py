"""Shared world item definitions for the database facade."""

from __future__ import annotations

import sqlite3

from ...world import Item, NotFoundError


class DatabaseWorldItemsMixin:
    """Persist item definitions shared by world inventories."""

    def create_item(
        self,
        item_id: str,
        name: str,
        description: str | None = None,
        *,
        stackable: bool = True,
    ) -> Item:
        item_id = self._clean_identifier(item_id, "Item ID")
        name = self._clean_name(name, "Item name")
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO items (id, name, description, stackable) VALUES (?, ?, ?, ?)",
                    (item_id, name, description, int(stackable)),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Item '{item_id}' already exists.") from error
        return Item(item_id, name, description, stackable)

    def upsert_item(
        self,
        item_id: str,
        name: str,
        description: str | None = None,
        *,
        stackable: bool = True,
    ) -> Item:
        """Make a catalog item available to room and entity inventories."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO items (id, name, description, stackable)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    stackable = excluded.stackable
                """,
                (item_id, name, description, int(stackable)),
            )
        return Item(item_id, name, description, stackable)

    @staticmethod
    def _require_item(connection: sqlite3.Connection, item_id: str) -> Item:
        row = connection.execute(
            "SELECT id, name, description, stackable FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Item '{item_id}' does not exist.")
        return Item(row["id"], row["name"], row["description"], bool(row["stackable"]))
