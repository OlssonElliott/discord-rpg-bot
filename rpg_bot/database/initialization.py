"""Database bootstrap and cross-domain schema initialization."""

from __future__ import annotations

from pathlib import Path

from ..inventory import DEFAULT_BASE_SLOTS


class DatabaseInitializationMixin:
    """Initialize database schemas, migrations, and shared bootstrap state."""

    def initialize(self) -> None:
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._initialize_characters(connection)
            self._initialize_world(connection)
            connection_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(room_connections)")
            }
            if "trap_disarm_difficulty" not in connection_columns:
                connection.execute(
                    "ALTER TABLE room_connections "
                    "ADD COLUMN trap_disarm_difficulty INTEGER "
                    "CHECK (trap_disarm_difficulty BETWEEN 1 AND 30)"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_known_traps (
                    character_id INTEGER NOT NULL,
                    connection_id TEXT NOT NULL,
                    PRIMARY KEY (character_id, connection_id),
                    FOREIGN KEY (character_id) REFERENCES characters(id),
                    FOREIGN KEY (connection_id) REFERENCES room_connections(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    discord_user_id INTEGER PRIMARY KEY,
                    dice_color TEXT NOT NULL,
                    dice_edge_color TEXT NOT NULL DEFAULT '#303030',
                    dice_number_color TEXT NOT NULL DEFAULT '#101010',
                    dm_portrait_key TEXT
                )
                """
            )
            preference_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_preferences)")
            }
            if "dice_edge_color" not in preference_columns:
                connection.execute(
                    """
                    ALTER TABLE user_preferences
                    ADD COLUMN dice_edge_color TEXT NOT NULL DEFAULT '#303030'
                    """
                )
            if "dice_number_color" not in preference_columns:
                connection.execute(
                    """
                    ALTER TABLE user_preferences
                    ADD COLUMN dice_number_color TEXT NOT NULL DEFAULT '#101010'
                    """
                )
            if "dm_portrait_key" not in preference_columns:
                connection.execute(
                    "ALTER TABLE user_preferences ADD COLUMN dm_portrait_key TEXT"
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_sheet_messages (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    character_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id, character_id),
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_inventories (
                    character_id INTEGER PRIMARY KEY,
                    total_storage INTEGER NOT NULL DEFAULT 4 CHECK (total_storage >= 0),
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_sheet_view_states (
                    character_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    discord_channel_id INTEGER NOT NULL,
                    discord_message_id INTEGER,
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY
                )
                """
            )
            slots_migration = "inventory_base_slots_4"
            if connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = ?",
                (slots_migration,),
            ).fetchone() is None:
                connection.execute(
                    "UPDATE character_inventories SET total_storage = ? "
                    "WHERE total_storage = 20",
                    (DEFAULT_BASE_SLOTS,),
                )
                connection.execute(
                    "INSERT INTO schema_migrations (name) VALUES (?)",
                    (slots_migration,),
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_wallets (
                    character_id INTEGER PRIMARY KEY,
                    copper INTEGER NOT NULL DEFAULT 0 CHECK (copper >= 0),
                    silver INTEGER NOT NULL DEFAULT 0 CHECK (silver >= 0),
                    gold INTEGER NOT NULL DEFAULT 0 CHECK (gold >= 0),
                    FOREIGN KEY (character_id) REFERENCES characters(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS character_items (
                    instance_id TEXT PRIMARY KEY,
                    character_id INTEGER NOT NULL,
                    template_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
                    durability INTEGER,
                    parent_container_id TEXT,
                    FOREIGN KEY (character_id) REFERENCES characters(id),
                    FOREIGN KEY (parent_container_id) REFERENCES character_items(instance_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS give_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_user_id INTEGER NOT NULL,
                    recipient_user_id INTEGER NOT NULL,
                    sender_character_id INTEGER,
                    recipient_character_id INTEGER,
                    item_instance_id TEXT,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    copper INTEGER NOT NULL DEFAULT 0,
                    silver INTEGER NOT NULL DEFAULT 0,
                    gold INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    sender_channel_id INTEGER,
                    sender_message_id INTEGER,
                    recipient_channel_id INTEGER,
                    recipient_message_id INTEGER
                )
                """
            )
            give_request_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(give_requests)")
            }
            for column in ("sender_channel_id", "sender_message_id"):
                if column not in give_request_columns:
                    connection.execute(f"ALTER TABLE give_requests ADD COLUMN {column} INTEGER")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS pending_give_requests_by_sender "
                "ON give_requests(sender_user_id, status, id DESC)"
            )
            self._initialize_character_equipment(connection)
            # The old model allowed nested item trees. Inventory is now flat and
            # an equipped container contributes capacity instead.
            connection.execute(
                """
                UPDATE character_items
                SET parent_container_id = NULL
                WHERE parent_container_id IS NOT NULL
                """
            )
            self._ensure_default_clothing(connection)
            connection.execute("PRAGMA optimize")
