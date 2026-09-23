"""Character inventory persistence for the database facade."""

from __future__ import annotations

from uuid import uuid4

from ..errors import CharacterNotFoundError
from ...inventory import (
    DEFAULT_BASE_SLOTS,
    EquipmentSlot,
    InventoryState,
    ItemInstance,
)


class DatabaseCharacterInventoryMixin:
    """Persist character inventory, equipment, wallets, and item placement."""

    def get_character_inventory(
        self, character_id: int, total_storage: int = DEFAULT_BASE_SLOTS
    ) -> InventoryState:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO character_inventories (character_id, total_storage)
                VALUES (?, ?)
                """,
                (character_id, total_storage),
            )
            inventory_row = connection.execute(
                """
                SELECT inventory.total_storage, characters.strength
                FROM character_inventories AS inventory
                JOIN characters ON characters.id = inventory.character_id
                WHERE inventory.character_id = ?
                """,
                (character_id,),
            ).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO character_wallets (character_id) VALUES (?)",
                (character_id,),
            )
            wallet_row = connection.execute(
                "SELECT copper, silver, gold FROM character_wallets WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            item_rows = connection.execute(
                """
                SELECT instance_id, character_id, template_id, quantity,
                       durability, parent_container_id
                FROM character_items WHERE character_id = ?
                ORDER BY rowid
                """,
                (character_id,),
            ).fetchall()
            equipment_rows = connection.execute(
                """
                SELECT slot, item_instance_id FROM character_equipment
                WHERE character_id = ?
                """,
                (character_id,),
            ).fetchall()
        return InventoryState(
            character_id=character_id,
            total_storage=inventory_row["total_storage"],
            items=tuple(
                ItemInstance(
                    instance_id=row["instance_id"],
                    character_id=row["character_id"],
                    template_id=row["template_id"],
                    quantity=row["quantity"],
                    durability=row["durability"],
                    parent_container_id=row["parent_container_id"],
                )
                for row in item_rows
            ),
            equipment={
                EquipmentSlot(row["slot"]): row["item_instance_id"]
                for row in equipment_rows
            },
            strength=inventory_row["strength"],
            copper=wallet_row["copper"],
            silver=wallet_row["silver"],
            gold=wallet_row["gold"],
        )

    def add_currency(
        self,
        character_id: int,
        *,
        copper: int = 0,
        silver: int = 0,
        gold: int = 0,
    ) -> InventoryState:
        if copper < 0 or silver < 0 or gold < 0:
            raise ValueError("Currency amounts cannot be negative.")
        if copper == silver == gold == 0:
            raise ValueError("At least one currency amount must be greater than zero.")
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone() is None:
                raise CharacterNotFoundError("That character does not exist.")
            connection.execute(
                "INSERT OR IGNORE INTO character_wallets (character_id) VALUES (?)",
                (character_id,),
            )
            connection.execute(
                """
                UPDATE character_wallets
                SET copper = copper + ?, silver = silver + ?, gold = gold + ?
                WHERE character_id = ?
                """,
                (copper, silver, gold, character_id),
            )
        return self.get_character_inventory(character_id)

    def add_inventory_item(
        self,
        character_id: int,
        template_id: str,
        *,
        quantity: int = 1,
        durability: int | None = None,
        parent_container_id: str | None = None,
        stackable: bool = False,
    ) -> str:
        if quantity <= 0:
            raise ValueError("Item quantity must be greater than zero.")
        with self._connect() as connection:
            if stackable:
                rows = connection.execute(
                    """
                    SELECT instance_id, quantity FROM character_items
                    WHERE character_id = ? AND template_id = ?
                      AND parent_container_id IS ?
                    ORDER BY rowid
                    """,
                    (character_id, template_id, parent_container_id),
                ).fetchall()
                if rows:
                    primary = rows[0]
                    combined_quantity = quantity + sum(
                        row["quantity"] for row in rows
                    )
                    connection.execute(
                        """
                        UPDATE character_items SET quantity = ?
                        WHERE instance_id = ?
                        """,
                        (combined_quantity, primary["instance_id"]),
                    )
                    duplicate_ids = [
                        row["instance_id"] for row in rows[1:]
                    ]
                    if duplicate_ids:
                        placeholders = ", ".join("?" for _ in duplicate_ids)
                        connection.execute(
                            f"""
                            DELETE FROM character_items
                            WHERE instance_id IN ({placeholders})
                            """,
                            duplicate_ids,
                        )
                    return primary["instance_id"]
            instance_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO character_items (
                    instance_id, character_id, template_id, quantity,
                    durability, parent_container_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    instance_id,
                    character_id,
                    template_id,
                    quantity,
                    durability,
                    parent_container_id,
                ),
            )
        return instance_id

    def move_inventory_item(
        self, character_id: int, instance_id: str, parent_container_id: str | None
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE character_items SET parent_container_id = ?
                WHERE character_id = ? AND instance_id = ?
                """,
                (parent_container_id, character_id, instance_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("That item is not in this inventory.")

    def equip_inventory_item(
        self,
        character_id: int,
        instance_id: str,
        slot: EquipmentSlot,
        *,
        clear_off_hand: bool = False,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE character_items SET parent_container_id = NULL
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            )
            connection.execute(
                """
                DELETE FROM character_equipment
                WHERE character_id = ? AND item_instance_id = ?
                """,
                (character_id, instance_id),
            )
            slots_to_clear = [slot.value]
            if clear_off_hand:
                slots_to_clear.append(EquipmentSlot.OFF_HAND.value)
            placeholders = ", ".join("?" for _ in slots_to_clear)
            connection.execute(
                f"""
                DELETE FROM character_equipment
                WHERE character_id = ? AND slot IN ({placeholders})
                """,
                (character_id, *slots_to_clear),
            )
            connection.execute(
                """
                INSERT INTO character_equipment (character_id, slot, item_instance_id)
                VALUES (?, ?, ?)
                """,
                (character_id, slot.value, instance_id),
            )

    def unequip_inventory_slot(
        self, character_id: int, slot: EquipmentSlot
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM character_equipment WHERE character_id = ? AND slot = ?",
                (character_id, slot.value),
            )

    def set_inventory_item_quantity(
        self, character_id: int, instance_id: str, quantity: int
    ) -> None:
        with self._connect() as connection:
            if quantity <= 0:
                connection.execute(
                    """
                    DELETE FROM character_items
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (character_id, instance_id),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE character_items SET quantity = ?
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (quantity, character_id, instance_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("That item is not in this inventory.")

    def character_has_usable_item(self, character_id: int, template_id: str) -> bool:
        """Return whether a character carries an unbroken instance of an item."""
        normalized = template_id.strip()
        if not normalized:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM character_items
                WHERE character_id = ?
                  AND template_id = ? COLLATE NOCASE
                  AND (durability IS NULL OR durability > 0)
                LIMIT 1
                """,
                (character_id, normalized),
            ).fetchone()
        return row is not None

    def break_character_item(self, character_id: int, template_id: str) -> bool:
        """Break one usable carried item instance and return whether one was found."""
        normalized = template_id.strip()
        if not normalized:
            return False
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT instance_id
                FROM character_items
                WHERE character_id = ?
                  AND template_id = ? COLLATE NOCASE
                  AND (durability IS NULL OR durability > 0)
                ORDER BY rowid
                LIMIT 1
                """,
                (character_id, normalized),
            ).fetchone()
            if row is None:
                return False
            if normalized == "trap_disarm_kit":
                connection.execute(
                    "DELETE FROM character_items WHERE instance_id = ?",
                    (row["instance_id"],),
                )
            else:
                connection.execute(
                    "UPDATE character_items SET durability = 0 WHERE instance_id = ?",
                    (row["instance_id"],),
                )
        return True
