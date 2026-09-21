"""SQLite persistence for RPG characters."""

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path
from datetime import datetime, timezone
import math
import sqlite3
from uuid import uuid4

from .dice_visuals import (
    DEFAULT_DICE_COLOR,
    DEFAULT_DICE_EDGE_COLOR,
    DEFAULT_DICE_NUMBER_COLOR,
    normalize_dice_color,
)
from .models import (
    Character,
    CharacterCombatState,
    CharacterCombatStatus,
    CharacterSheetViewState,
    Stance,
)
from .dungeon import (
    CharacterLocation,
    CharacterRoomKnowledge,
    ConnectionType,
    TrapDamageType,
    TrapState,
    Dungeon,
    Floor,
    GameLock,
    KnowledgeSource,
    KnowledgeState,
    PlayerViewState,
    RoomConnection,
)
from .inventory import (
    DEFAULT_BASE_SLOTS,
    DEFAULT_CLOTHING_TEMPLATE_ID,
    EquipmentSlot,
    InventoryState,
    ItemInstance,
)
from .portraits import default_portrait_key
from .world import (
    Area,
    AreaGraph,
    EntityKind,
    Exit,
    GraphConnection,
    HolderKind,
    InvalidMovementError,
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
    NotFoundError,
    Room,
    RoomEditorNode,
    MovementResult,
    WorldEntity,
)


class CharacterAlreadyExistsError(ValueError):
    pass


class CharacterNotFoundError(ValueError):
    pass


class InvalidHitPointsError(ValueError):
    pass


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def get_character_skill_rank(self, character_id: int, skill: str) -> int:
        """Return a case-insensitive skill-tree rank, or zero if it is unknown."""
        normalized = skill.strip()
        if not normalized:
            return 0
        with self._connect() as connection:
            row = connection.execute(
                "SELECT rank FROM character_skills "
                "WHERE character_id = ? AND skill = ? COLLATE NOCASE",
                (character_id, normalized),
            ).fetchone()
        return int(row["rank"]) if row is not None else 0

    def get_character_attribute(self, character_id: int, attribute: str) -> int:
        """Return a persisted character attribute, defaulting an unset score to 10."""
        normalized = attribute.casefold().strip()
        allowed_attributes = {
            "strength",
            "dexterity",
            "arcana",
            "vitality",
            "insight",
            "personality",
        }
        if normalized not in allowed_attributes:
            raise ValueError(f"Unknown character attribute '{attribute}'.")

        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {normalized} FROM characters WHERE id = ?",
                (character_id,),
            ).fetchone()
        if row is None:
            raise CharacterNotFoundError(f"Character {character_id} does not exist.")
        value = row[normalized]
        return int(value) if value is not None else 10

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

    @staticmethod
    def _create_character_equipment_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_equipment (
                character_id INTEGER NOT NULL,
                slot TEXT NOT NULL CHECK (
                    slot IN ('main_hand', 'off_hand', 'clothing', 'armor', 'container')
                ),
                item_instance_id TEXT NOT NULL,
                PRIMARY KEY (character_id, slot),
                UNIQUE (character_id, item_instance_id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (item_instance_id) REFERENCES character_items(instance_id)
            )
            """
        )

    @classmethod
    def _initialize_character_equipment(cls, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            """
            SELECT sql FROM sqlite_schema
            WHERE type = 'table' AND name = 'character_equipment'
            """
        ).fetchone()
        if row is None:
            cls._create_character_equipment_table(connection)
            return
        if "'clothing'" in (row["sql"] or ""):
            return
        connection.execute(
            "ALTER TABLE character_equipment RENAME TO character_equipment_legacy"
        )
        cls._create_character_equipment_table(connection)
        connection.execute(
            """
            INSERT INTO character_equipment (character_id, slot, item_instance_id)
            SELECT character_id, slot, item_instance_id
            FROM character_equipment_legacy
            """
        )
        connection.execute("DROP TABLE character_equipment_legacy")

    @staticmethod
    def _ensure_default_clothing(
        connection: sqlite3.Connection, character_id: int | None = None
    ) -> None:
        parameters: tuple[int, ...] = ()
        character_filter = ""
        if character_id is not None:
            character_filter = "WHERE id = ?"
            parameters = (character_id,)
        character_rows = connection.execute(
            f"SELECT id FROM characters {character_filter} ORDER BY id",
            parameters,
        ).fetchall()
        for character_row in character_rows:
            existing = connection.execute(
                """
                SELECT instance_id FROM character_items
                WHERE character_id = ? AND template_id = ?
                ORDER BY rowid LIMIT 1
                """,
                (character_row["id"], DEFAULT_CLOTHING_TEMPLATE_ID),
            ).fetchone()
            if existing is not None:
                continue
            instance_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO character_items (
                    instance_id, character_id, template_id, quantity, durability
                ) VALUES (?, ?, ?, 1, NULL)
                """,
                (instance_id, character_row["id"], DEFAULT_CLOTHING_TEMPLATE_ID),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO character_equipment (
                    character_id, slot, item_instance_id
                ) VALUES (?, 'clothing', ?)
                """,
                (character_row["id"], instance_id),
            )

    @staticmethod
    def _create_characters_table(
        connection: sqlite3.Connection,
        table_name: str = "characters",
    ) -> None:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                hp INTEGER NOT NULL CHECK (hp >= -max_hp AND hp <= max_hp),
                max_hp INTEGER NOT NULL CHECK (max_hp > 0),
                stance TEXT NOT NULL CHECK (
                    stance IN ('steady', 'bad_stance', 'prone')
                ),
                lineage TEXT,
                race TEXT,
                age TEXT,
                gender TEXT,
                strength INTEGER,
                dexterity INTEGER,
                arcana INTEGER,
                vitality INTEGER,
                insight INTEGER,
                personality INTEGER,
                portrait_key TEXT,
                current_room_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
            )
            """
        )

    @classmethod
    def _create_character_tables(cls, connection: sqlite3.Connection) -> None:
        cls._create_characters_table(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_skills (
                character_id INTEGER NOT NULL,
                skill TEXT NOT NULL,
                rank INTEGER NOT NULL CHECK (rank > 0),
                PRIMARY KEY (character_id, skill),
                FOREIGN KEY (character_id) REFERENCES characters(id)
            )
            """
        )

    @classmethod
    def _migrate_character_hp_constraint(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        row = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'characters'
            """
        ).fetchone()
        table_sql = (row["sql"] if row is not None else "") or ""
        normalized_sql = "".join(table_sql.casefold().split())
        if "hp>=-max_hp" in normalized_sql:
            return

        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("DROP TABLE IF EXISTS characters_new")
            cls._create_characters_table(connection, "characters_new")
            connection.execute(
                """
                INSERT INTO characters_new (
                    id, discord_user_id, name, hp, max_hp, stance,
                    lineage, race, age, gender,
                    strength, dexterity, arcana, vitality, insight, personality,
                    portrait_key, current_room_id, is_active, is_archived
                )
                SELECT
                    id, discord_user_id, name, hp, max_hp, stance,
                    lineage, race, age, gender,
                    strength, dexterity, arcana, vitality, insight, personality,
                    portrait_key, current_room_id, is_active, is_archived
                FROM characters
                """
            )
            connection.execute("DROP TABLE characters")
            connection.execute(
                "ALTER TABLE characters_new RENAME TO characters"
            )
            connection.commit()
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _initialize_character_combat_states(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS character_combat_states (
                character_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'active' CHECK (
                    status IN ('active', 'downed', 'stable', 'recovering', 'dead')
                ),
                failed_death_saves INTEGER NOT NULL DEFAULT 0 CHECK (
                    failed_death_saves BETWEEN 0 AND 3
                ),
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO character_combat_states (
                character_id, status, failed_death_saves
            )
            SELECT
                id,
                CASE
                    WHEN hp <= -max_hp THEN 'dead'
                    WHEN hp <= 0 THEN 'downed'
                    ELSE 'active'
                END,
                0
            FROM characters
            """
        )

    @classmethod
    def _initialize_characters(cls, connection: sqlite3.Connection) -> None:
        character_table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'characters'"
        ).fetchone()
        if not character_table_exists:
            cls._create_character_tables(connection)
        else:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(characters)")
            }
            profile_migrations = {
                "lineage": "ALTER TABLE characters ADD COLUMN lineage TEXT",
                "race": "ALTER TABLE characters ADD COLUMN race TEXT",
                "age": "ALTER TABLE characters ADD COLUMN age TEXT",
                "gender": "ALTER TABLE characters ADD COLUMN gender TEXT",
                "strength": "ALTER TABLE characters ADD COLUMN strength INTEGER",
                "dexterity": "ALTER TABLE characters ADD COLUMN dexterity INTEGER",
                "arcana": "ALTER TABLE characters ADD COLUMN arcana INTEGER",
                "vitality": "ALTER TABLE characters ADD COLUMN vitality INTEGER",
                "insight": "ALTER TABLE characters ADD COLUMN insight INTEGER",
                "personality": "ALTER TABLE characters ADD COLUMN personality INTEGER",
                "portrait_key": "ALTER TABLE characters ADD COLUMN portrait_key TEXT",
                "current_room_id": "ALTER TABLE characters ADD COLUMN current_room_id TEXT",
            }
            for column, statement in profile_migrations.items():
                if column not in columns:
                    connection.execute(statement)

            if "id" not in columns:
                skills_exist = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'character_skills'
                    """
                ).fetchone()
                if skills_exist:
                    connection.execute(
                        "ALTER TABLE character_skills RENAME TO character_skills_legacy"
                    )
                connection.execute("ALTER TABLE characters RENAME TO characters_legacy")
                cls._create_character_tables(connection)
                connection.execute(
                    """
                    INSERT INTO characters (
                        discord_user_id, name, hp, max_hp, stance,
                        lineage, race, age, gender,
                        strength, dexterity, arcana, vitality, insight, personality,
                        portrait_key,
                        is_active, is_archived
                    )
                    SELECT discord_user_id, name, hp, max_hp, stance,
                           lineage, race, age, gender,
                           strength, dexterity, arcana, vitality, insight, personality,
                           portrait_key,
                           1, 0
                    FROM characters_legacy
                    """
                )
                if skills_exist:
                    connection.execute(
                        """
                        INSERT INTO character_skills (character_id, skill, rank)
                        SELECT characters.id, legacy.skill, legacy.rank
                        FROM character_skills_legacy AS legacy
                        JOIN characters
                          ON characters.discord_user_id = legacy.discord_user_id
                        """
                    )
                    connection.execute("DROP TABLE character_skills_legacy")
                connection.execute("DROP TABLE characters_legacy")
            else:
                current_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(characters)")
                }
                if "is_active" not in current_columns:
                    connection.execute(
                        "ALTER TABLE characters ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
                    )
                if "is_archived" not in current_columns:
                    connection.execute(
                        "ALTER TABLE characters ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0"
                    )
                cls._migrate_character_hp_constraint(connection)
                cls._create_character_tables(connection)

        cls._initialize_character_combat_states(connection)
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_character_per_user
            ON characters(discord_user_id)
            WHERE is_active = 1 AND is_archived = 0
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS unique_selectable_character_name
            ON characters(discord_user_id, name COLLATE NOCASE)
            WHERE is_archived = 0
            """
        )

    @staticmethod
    def _initialize_world(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS areas (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT
            );
            CREATE TABLE IF NOT EXISTS rooms (
                id TEXT PRIMARY KEY,
                area_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                floor_id TEXT,
                width REAL NOT NULL DEFAULT 1,
                height REAL NOT NULL DEFAULT 1,
                scene_image_path TEXT,
                scene_image_url TEXT,
                scene_prompt TEXT,
                FOREIGN KEY (area_id) REFERENCES areas(id)
            );
            CREATE TABLE IF NOT EXISTS room_exits (
                room_id TEXT NOT NULL,
                name TEXT NOT NULL COLLATE NOCASE,
                destination_room_id TEXT NOT NULL,
                PRIMARY KEY (room_id, name),
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (destination_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS room_editor_metadata (
                room_id TEXT PRIMARY KEY,
                x REAL NOT NULL,
                y REAL NOT NULL,
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS world_entities (
                id TEXT PRIMARY KEY,
                room_id TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('enemy', 'npc', 'container')),
                name TEXT NOT NULL,
                description TEXT,
                FOREIGN KEY (room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS enemy_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                race TEXT NOT NULL DEFAULT 'Unknown',
                difficulty_level INTEGER NOT NULL DEFAULT 1 CHECK (difficulty_level >= 0),
                strength INTEGER NOT NULL DEFAULT 0 CHECK (strength >= 0),
                dexterity INTEGER NOT NULL DEFAULT 0 CHECK (dexterity >= 0),
                arcana INTEGER NOT NULL DEFAULT 0 CHECK (arcana >= 0),
                vitality INTEGER NOT NULL DEFAULT 0 CHECK (vitality >= 0),
                insight INTEGER NOT NULL DEFAULT 0 CHECK (insight >= 0),
                personality INTEGER NOT NULL DEFAULT 0 CHECK (personality >= 0),
                max_hp INTEGER NOT NULL DEFAULT 7 CHECK (max_hp > 0),
                armor INTEGER NOT NULL DEFAULT 0 CHECK (armor >= 0),
                magical_resistance INTEGER NOT NULL DEFAULT 0 CHECK (magical_resistance >= 0),
                attack_dc INTEGER NOT NULL DEFAULT 12 CHECK (attack_dc > 0),
                defense_dc INTEGER NOT NULL DEFAULT 12 CHECK (defense_dc > 0),
                damage TEXT NOT NULL DEFAULT '1d4',
                attack_profile TEXT NOT NULL DEFAULT 'Basic attack',
                special_ability TEXT,
                typical_behaviour TEXT NOT NULL DEFAULT 'Unknown',
                main_hand_item_id TEXT,
                off_hand_item_id TEXT,
                armor_item_id TEXT
            );
            CREATE TABLE IF NOT EXISTS world_enemies (
                entity_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                current_hp INTEGER NOT NULL CHECK (current_hp >= 0),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'dead', 'fled')),
                FOREIGN KEY (entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (template_id) REFERENCES enemy_templates(id)
            );
            CREATE INDEX IF NOT EXISTS world_enemies_by_template
                ON world_enemies(template_id);
            CREATE TABLE IF NOT EXISTS world_seed_state (
                key TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS container_templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                container_type TEXT NOT NULL,
                description TEXT,
                default_has_lock INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_has_lock IN (0, 1)
                ),
                default_is_locked INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_is_locked IN (0, 1)
                ),
                default_is_broken INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_is_broken IN (0, 1)
                ),
                default_unlock_difficulty INTEGER CHECK (
                    default_unlock_difficulty BETWEEN 1 AND 30
                ),
                default_hidden INTEGER NOT NULL DEFAULT 0 CHECK (
                    default_hidden IN (0, 1)
                ),
                default_discovery_difficulty INTEGER CHECK (
                    default_discovery_difficulty BETWEEN 1 AND 30
                )
            );
            CREATE TABLE IF NOT EXISTS world_containers (
                entity_id TEXT PRIMARY KEY,
                template_id TEXT NOT NULL,
                has_lock INTEGER NOT NULL DEFAULT 0 CHECK (has_lock IN (0, 1)),
                is_locked INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1)),
                is_broken INTEGER NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1)),
                unlock_difficulty INTEGER CHECK (
                    unlock_difficulty BETWEEN 1 AND 30
                ),
                hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
                discovery_difficulty INTEGER CHECK (
                    discovery_difficulty BETWEEN 1 AND 30
                ),
                is_open INTEGER NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1)),
                searched INTEGER NOT NULL DEFAULT 0 CHECK (searched IN (0, 1)),
                FOREIGN KEY (entity_id) REFERENCES world_entities(id) ON DELETE CASCADE,
                FOREIGN KEY (template_id) REFERENCES container_templates(id)
            );
            CREATE TABLE IF NOT EXISTS character_known_containers (
                character_id INTEGER NOT NULL,
                container_id TEXT NOT NULL,
                PRIMARY KEY (character_id, container_id),
                FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
                FOREIGN KEY (container_id) REFERENCES world_entities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS containers_by_template
                ON world_containers(template_id);
            INSERT OR IGNORE INTO container_templates (
                id, name, container_type, default_has_lock, default_is_locked,
                default_is_broken, default_unlock_difficulty, default_hidden,
                default_discovery_difficulty
            ) VALUES
                ('wooden_chest', 'Wooden Chest', 'wooden_chest', 0, 0, 0, NULL, 0, NULL),
                ('reinforced_chest', 'Reinforced Chest', 'reinforced_chest', 1, 1, 0, 14, 0, NULL),
                ('barrel', 'Barrel', 'barrel', 0, 0, 0, NULL, 0, NULL),
                ('crate', 'Crate', 'crate', 0, 0, 0, NULL, 0, NULL),
                ('shelf', 'Shelf', 'shelf', 0, 0, 0, NULL, 0, NULL),
                ('bookshelf', 'Bookshelf', 'bookshelf', 0, 0, 0, NULL, 0, NULL),
                ('corpse', 'Corpse', 'corpse', 0, 0, 0, NULL, 0, NULL),
                ('skeleton', 'Skeleton', 'skeleton', 0, 0, 0, NULL, 0, NULL),
                ('backpack', 'Backpack', 'backpack', 0, 0, 0, NULL, 0, NULL),
                ('hidden_compartment', 'Hidden Compartment', 'hidden_compartment', 0, 0, 0, NULL, 1, 14),
                ('loose_floorboard', 'Loose Floorboard', 'loose_floorboard', 0, 0, 0, NULL, 1, 14),
                ('other', 'Other', 'other', 0, 0, 0, NULL, 0, NULL);
            INSERT OR IGNORE INTO world_containers (
                entity_id, template_id, has_lock, is_locked, is_broken,
                unlock_difficulty, hidden, discovery_difficulty, is_open, searched
            )
            SELECT id, 'other', 0, 0, 0, NULL, 0, NULL, 0, 0
            FROM world_entities
            WHERE kind = 'container';
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                stackable INTEGER NOT NULL DEFAULT 1 CHECK (stackable IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS inventory_stacks (
                holder_kind TEXT NOT NULL CHECK (
                    holder_kind IN ('character', 'room', 'entity')
                ),
                holder_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                PRIMARY KEY (holder_kind, holder_id, item_id),
                FOREIGN KEY (item_id) REFERENCES items(id)
            );
            CREATE INDEX IF NOT EXISTS entities_by_room ON world_entities(room_id);
            CREATE INDEX IF NOT EXISTS characters_by_room ON characters(current_room_id);
            """
        )
        enemy_seed_key = "basic_enemy_templates_v1"
        if connection.execute(
            "SELECT 1 FROM world_seed_state WHERE key = ?",
            (enemy_seed_key,),
        ).fetchone() is None:
            connection.executemany(
                """
                INSERT OR IGNORE INTO enemy_templates (
                    id, name, description, race, difficulty_level,
                    strength, dexterity, arcana, vitality, insight, personality,
                    max_hp, armor, magical_resistance, attack_dc, defense_dc,
                    damage, attack_profile, special_ability, typical_behaviour
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    (
                        "core_goblin_raider",
                        "Goblin Raider",
                        "A wiry goblin skirmisher accustomed to ambushes and dirty fighting.",
                        "Goblin",
                        1, 1, 3, 0, 1, 1, 0, 6, 0, 0, 12, 13,
                        "1d4",
                        "Jagged blade or shortbow",
                        "Pack opportunist",
                        "Circles isolated targets, attacks from advantage, and retreats when pressured.",
                    ),
                    (
                        "core_bandit",
                        "Bandit",
                        "A common outlaw with practical weapons and little discipline.",
                        "Human",
                        1, 2, 2, 0, 2, 1, 1, 9, 1, 0, 12, 12,
                        "1d6",
                        "Sword or club",
                        None,
                        "Fights directly while an advantage remains and may flee when badly hurt.",
                    ),
                    (
                        "core_skeleton_warrior",
                        "Skeleton Warrior",
                        "An animated warrior held together by old armor and darker forces.",
                        "Undead",
                        2, 3, 1, 0, 3, 0, 0, 10, 1, 1, 13, 11,
                        "1d6",
                        "Heavy weapon swing",
                        "Fearless",
                        "Advances without hesitation and keeps pressure on the nearest living target.",
                    ),
                    (
                        "core_bone_hound",
                        "Bone Hound",
                        "A fast skeletal predator that hunts by sound and movement.",
                        "Undead Beast",
                        2, 2, 4, 0, 2, 2, 0, 8, 0, 1, 13, 13,
                        "1d6",
                        "Bite and maul",
                        "Relentless pursuit",
                        "Rushes vulnerable targets and stays close once it has engaged.",
                    ),
                    (
                        "core_cultist",
                        "Cultist",
                        "A fanatical occultist carrying crude weapons and unstable magic.",
                        "Human",
                        2, 1, 2, 4, 1, 2, 2, 7, 0, 2, 13, 11,
                        "1d4",
                        "Ritual blade or dark bolt",
                        "Dark invocation",
                        "Keeps distance when possible and supports stronger allies with occult pressure.",
                    ),
                    (
                        "core_swamp_troll",
                        "Swamp Troll",
                        "A massive troll accustomed to fighting through wounds that would stop lesser creatures.",
                        "Troll",
                        4, 6, 1, 0, 6, 1, 0, 28, 2, 1, 15, 10,
                        "2d6",
                        "Crushing claw or heavy club",
                        "Regeneration",
                        "Pushes into the center of a fight and focuses on the nearest threatening target.",
                    ),
                ),
            )
            connection.execute(
                "INSERT INTO world_seed_state (key) VALUES (?)",
                (enemy_seed_key,),
            )
        room_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(rooms)")
        }
        room_migrations = {
            "floor_id": "ALTER TABLE rooms ADD COLUMN floor_id TEXT",
            "width": "ALTER TABLE rooms ADD COLUMN width REAL NOT NULL DEFAULT 1",
            "height": "ALTER TABLE rooms ADD COLUMN height REAL NOT NULL DEFAULT 1",
            "scene_image_path": "ALTER TABLE rooms ADD COLUMN scene_image_path TEXT",
            "scene_image_url": "ALTER TABLE rooms ADD COLUMN scene_image_url TEXT",
            "scene_prompt": "ALTER TABLE rooms ADD COLUMN scene_prompt TEXT",
        }
        for column, statement in room_migrations.items():
            if column not in room_columns:
                connection.execute(statement)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dungeon_floors (
                id TEXT PRIMARY KEY,
                dungeon_id TEXT NOT NULL,
                floor_number INTEGER NOT NULL,
                name TEXT NOT NULL,
                UNIQUE (dungeon_id, floor_number),
                FOREIGN KEY (dungeon_id) REFERENCES areas(id)
            );
            CREATE TABLE IF NOT EXISTS room_connections (
                id TEXT PRIMARY KEY,
                from_room_id TEXT NOT NULL,
                to_room_id TEXT NOT NULL,
                exit_name TEXT NOT NULL,
                return_exit_name TEXT,
                connection_type TEXT NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1)),
                bidirectional INTEGER NOT NULL DEFAULT 0 CHECK (bidirectional IN (0, 1)),
                has_lock INTEGER NOT NULL DEFAULT 0 CHECK (has_lock IN (0, 1)),
                is_locked INTEGER NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1)),
                is_broken INTEGER NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1)),
                is_open INTEGER NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1)),
                unlock_difficulty INTEGER CHECK (
                    unlock_difficulty BETWEEN 1 AND 30
                ),
                has_trap INTEGER NOT NULL DEFAULT 0 CHECK (has_trap IN (0, 1)),
                trap_state TEXT CHECK (
                    trap_state IN ('armed', 'disarmed', 'triggered')
                ),
                trap_detection_difficulty INTEGER CHECK (
                    trap_detection_difficulty BETWEEN 1 AND 30
                ),
                trap_damage_type TEXT,
                trap_damage INTEGER CHECK (trap_damage > 0),
                FOREIGN KEY (from_room_id) REFERENCES rooms(id),
                FOREIGN KEY (to_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS character_room_knowledge (
                character_id INTEGER NOT NULL,
                room_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('known', 'visited')),
                source TEXT NOT NULL CHECK (source IN ('discovered', 'shared')),
                first_visited_at TEXT,
                last_visited_at TEXT,
                last_seen_scene_id TEXT,
                shared_by_character_id INTEGER,
                PRIMARY KEY (character_id, room_id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (room_id) REFERENCES rooms(id),
                FOREIGN KEY (shared_by_character_id) REFERENCES characters(id)
            );
            CREATE TABLE IF NOT EXISTS character_known_connections (
                character_id INTEGER NOT NULL,
                connection_id TEXT NOT NULL,
                PRIMARY KEY (character_id, connection_id),
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (connection_id) REFERENCES room_connections(id)
            );
            CREATE TABLE IF NOT EXISTS player_view_states (
                character_id INTEGER PRIMARY KEY,
                selected_floor_id TEXT,
                focused_room_id TEXT,
                discord_channel_id INTEGER,
                discord_message_id INTEGER,
                FOREIGN KEY (character_id) REFERENCES characters(id),
                FOREIGN KEY (selected_floor_id) REFERENCES dungeon_floors(id),
                FOREIGN KEY (focused_room_id) REFERENCES rooms(id)
            );
            CREATE TABLE IF NOT EXISTS player_map_refresh_requests (
                character_id INTEGER PRIMARY KEY,
                requested_at TEXT NOT NULL,
                FOREIGN KEY (character_id) REFERENCES characters(id)
            );
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                lock_state TEXT NOT NULL CHECK (
                    lock_state IN ('none', 'movement_locked', 'all_actions_locked')
                )
            );
            INSERT OR IGNORE INTO game_state (id, lock_state) VALUES (1, 'none');
            """
        )
        connection_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(room_connections)")
        }
        connection_migrations = {
            "has_lock": (
                "ALTER TABLE room_connections ADD COLUMN has_lock INTEGER "
                "NOT NULL DEFAULT 1 CHECK (has_lock IN (0, 1))"
            ),
            "is_locked": (
                "ALTER TABLE room_connections ADD COLUMN is_locked INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_locked IN (0, 1))"
            ),
            "is_broken": (
                "ALTER TABLE room_connections ADD COLUMN is_broken INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_broken IN (0, 1))"
            ),
            "is_open": (
                "ALTER TABLE room_connections ADD COLUMN is_open INTEGER "
                "NOT NULL DEFAULT 0 CHECK (is_open IN (0, 1))"
            ),
            "unlock_difficulty": (
                "ALTER TABLE room_connections ADD COLUMN unlock_difficulty INTEGER "
                "CHECK (unlock_difficulty BETWEEN 1 AND 30)"
            ),
            "has_trap": (
                "ALTER TABLE room_connections ADD COLUMN has_trap INTEGER "
                "NOT NULL DEFAULT 0 CHECK (has_trap IN (0, 1))"
            ),
            "trap_state": (
                "ALTER TABLE room_connections ADD COLUMN trap_state TEXT "
                "CHECK (trap_state IN ('armed', 'disarmed', 'triggered'))"
            ),
            "trap_detection_difficulty": (
                "ALTER TABLE room_connections ADD COLUMN "
                "trap_detection_difficulty INTEGER "
                "CHECK (trap_detection_difficulty BETWEEN 1 AND 30)"
            ),
            "trap_damage_type": (
                "ALTER TABLE room_connections ADD COLUMN trap_damage_type TEXT"
            ),
            "trap_damage": (
                "ALTER TABLE room_connections ADD COLUMN trap_damage INTEGER "
                "CHECK (trap_damage > 0)"
            ),
        }
        for column, statement in connection_migrations.items():
            if column not in connection_columns:
                connection.execute(statement)
        connection.execute(
            """
            UPDATE room_connections
            SET trap_state = 'armed'
            WHERE has_trap = 1 AND trap_state IS NULL
            """
        )
        # Existing areas become dungeons with one default floor.  Existing room
        # layouts are preserved and assigned to that floor.
        for area in connection.execute("SELECT id, name FROM areas").fetchall():
            floor_id = f"{area['id']}:floor:1"
            connection.execute(
                """
                INSERT OR IGNORE INTO dungeon_floors (id, dungeon_id, floor_number, name)
                VALUES (?, ?, 1, 'Floor 1')
                """,
                (floor_id, area["id"]),
            )
            connection.execute(
                "UPDATE rooms SET floor_id = ? WHERE area_id = ? AND floor_id IS NULL",
                (floor_id, area["id"]),
            )
        # Give legacy exits stable connection IDs without changing movement data.
        for exit_row in connection.execute(
            "SELECT room_id, name, destination_room_id FROM room_exits"
        ).fetchall():
            exists = connection.execute(
                """
                SELECT 1 FROM room_connections
                WHERE (from_room_id = ? AND exit_name = ? COLLATE NOCASE)
                   OR (to_room_id = ? AND return_exit_name = ? COLLATE NOCASE)
                """,
                (
                    exit_row["room_id"], exit_row["name"],
                    exit_row["room_id"], exit_row["name"],
                ),
            ).fetchone()
            if exists is None:
                connection.execute(
                    """
                    INSERT INTO room_connections (
                        id, from_room_id, to_room_id, exit_name, connection_type,
                        hidden, bidirectional
                    ) VALUES (?, ?, ?, ?, 'passage', 0, 0)
                    """,
                    (
                        uuid4().hex,
                        exit_row["room_id"],
                        exit_row["destination_room_id"],
                        exit_row["name"],
                    ),
                )


    def list_container_templates(self):
        from .containers import ContainerTemplate, ContainerType

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, container_type, description,
                       default_has_lock, default_is_locked, default_is_broken,
                       default_unlock_difficulty, default_hidden,
                       default_discovery_difficulty
                FROM container_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(
            ContainerTemplate(
                row["id"],
                row["name"],
                ContainerType(row["container_type"]),
                row["description"],
                bool(row["default_has_lock"]),
                bool(row["default_is_locked"]),
                bool(row["default_is_broken"]),
                row["default_unlock_difficulty"],
                bool(row["default_hidden"]),
                row["default_discovery_difficulty"],
            )
            for row in rows
        )

    def get_container_template(self, template_id: str):
        from .containers import ContainerTemplate, ContainerType

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, container_type, description,
                       default_has_lock, default_is_locked, default_is_broken,
                       default_unlock_difficulty, default_hidden,
                       default_discovery_difficulty
                FROM container_templates WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return ContainerTemplate(
            row["id"],
            row["name"],
            ContainerType(row["container_type"]),
            row["description"],
            bool(row["default_has_lock"]),
            bool(row["default_is_locked"]),
            bool(row["default_is_broken"]),
            row["default_unlock_difficulty"],
            bool(row["default_hidden"]),
            row["default_discovery_difficulty"],
        )

    def create_container_template(self, template):
        template_id = self._clean_identifier(template.template_id, "Container template ID")
        name = self._clean_name(template.name, "Container name")
        from .locks import validate_lock

        unlock_difficulty = validate_lock(
            template.default_has_lock,
            template.default_is_locked,
            template.default_is_broken,
            template.default_unlock_difficulty,
            subject="container",
        )
        discovery_difficulty = self._validate_container_discovery(
            template.default_hidden,
            template.default_discovery_difficulty,
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO container_templates (
                        id, name, container_type, description,
                        default_has_lock, default_is_locked, default_is_broken,
                        default_unlock_difficulty, default_hidden,
                        default_discovery_difficulty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        template_id,
                        name,
                        template.container_type.value,
                        template.description,
                        int(template.default_has_lock),
                        int(template.default_is_locked),
                        int(template.default_is_broken),
                        unlock_difficulty,
                        int(template.default_hidden),
                        discovery_difficulty,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Container template '{template_id}' already exists."
                ) from error
        created = self.get_container_template(template_id)
        assert created is not None
        return created

    def update_container_template(self, template_id: str, template):
        clean_id = self._clean_identifier(template_id, "Container template ID")
        name = self._clean_name(template.name, "Container name")
        from .locks import validate_lock

        unlock_difficulty = validate_lock(
            template.default_has_lock,
            template.default_is_locked,
            template.default_is_broken,
            template.default_unlock_difficulty,
            subject="container",
        )
        discovery_difficulty = self._validate_container_discovery(
            template.default_hidden,
            template.default_discovery_difficulty,
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE container_templates
                SET name = ?, container_type = ?, description = ?,
                    default_has_lock = ?, default_is_locked = ?,
                    default_is_broken = ?, default_unlock_difficulty = ?,
                    default_hidden = ?, default_discovery_difficulty = ?
                WHERE id = ?
                """,
                (
                    name,
                    template.container_type.value,
                    template.description,
                    int(template.default_has_lock),
                    int(template.default_is_locked),
                    int(template.default_is_broken),
                    unlock_difficulty,
                    int(template.default_hidden),
                    discovery_difficulty,
                    clean_id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Container template '{clean_id}' does not exist."
                )
        updated = self.get_container_template(clean_id)
        assert updated is not None
        return updated

    def create_container_instance(
        self,
        room_id: str,
        template_id: str,
        *,
        instance_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        has_lock: bool | None = None,
        is_locked: bool | None = None,
        is_broken: bool | None = None,
        unlock_difficulty: int | None = None,
        hidden: bool | None = None,
        discovery_difficulty: int | None = None,
        is_open: bool = False,
        searched: bool = False,
    ):
        template = self.get_container_template(template_id)
        if template is None:
            raise NotFoundError(
                f"Container template '{template_id}' does not exist."
            )
        clean_id = self._clean_identifier(
            instance_id or f"{template.template_id}_{uuid4().hex[:12]}",
            "Container ID",
        )
        clean_name = self._clean_name(name or template.name, "Container name")
        resolved_has_lock = (
            template.default_has_lock if has_lock is None else has_lock
        )
        resolved_is_locked = (
            template.default_is_locked if is_locked is None else is_locked
        )
        resolved_is_broken = (
            template.default_is_broken if is_broken is None else is_broken
        )
        resolved_unlock_difficulty = (
            template.default_unlock_difficulty
            if unlock_difficulty is None and is_locked is None
            else unlock_difficulty
        )
        from .locks import validate_lock

        resolved_unlock_difficulty = validate_lock(
            resolved_has_lock,
            resolved_is_locked,
            resolved_is_broken,
            resolved_unlock_difficulty,
            subject="container",
        )
        if is_open and resolved_is_locked:
            raise ValueError("A locked container cannot be open.")
        resolved_hidden = template.default_hidden if hidden is None else hidden
        resolved_discovery_difficulty = (
            template.default_discovery_difficulty
            if discovery_difficulty is None and hidden is None
            else discovery_difficulty
        )
        resolved_discovery_difficulty = self._validate_container_discovery(
            resolved_hidden,
            resolved_discovery_difficulty,
        )
        resolved_description = (
            template.description if description is None else description
        )
        with self._connect() as connection:
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO world_entities (
                        id, room_id, kind, name, description
                    ) VALUES (?, ?, 'container', ?, ?)
                    """,
                    (clean_id, room_id, clean_name, resolved_description),
                )
                connection.execute(
                    """
                    INSERT INTO world_containers (
                        entity_id, template_id, has_lock, is_locked, is_broken,
                        unlock_difficulty, hidden, discovery_difficulty,
                        is_open, searched
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_id,
                        template.template_id,
                        int(resolved_has_lock),
                        int(resolved_is_locked),
                        int(resolved_is_broken),
                        resolved_unlock_difficulty,
                        int(resolved_hidden),
                        resolved_discovery_difficulty,
                        int(is_open),
                        int(searched),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Container '{clean_id}' already exists.") from error
        created = self.get_container_instance(clean_id)
        assert created is not None
        return created

    def get_container_instance(self, container_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT entity.id, entity.room_id,
                       COALESCE(container.template_id, 'other') AS template_id,
                       entity.name,
                       COALESCE(template.container_type, 'other') AS container_type,
                       entity.description,
                       COALESCE(container.has_lock, 0) AS has_lock,
                       COALESCE(container.is_locked, 0) AS is_locked,
                       COALESCE(container.is_broken, 0) AS is_broken,
                       container.unlock_difficulty,
                       COALESCE(container.hidden, 0) AS hidden,
                       container.discovery_difficulty,
                       COALESCE(container.is_open, 0) AS is_open,
                       COALESCE(container.searched, 0) AS searched
                FROM world_entities AS entity
                LEFT JOIN world_containers AS container
                  ON container.entity_id = entity.id
                LEFT JOIN container_templates AS template
                  ON template.id = container.template_id
                WHERE entity.id = ? AND entity.kind = 'container'
                """,
                (container_id,),
            ).fetchone()
        return self._container_instance_from_row(row) if row is not None else None

    def list_room_container_instances(self, room_id: str):
        with self._connect() as connection:
            self._require_room(connection, room_id)
            rows = connection.execute(
                """
                SELECT entity.id, entity.room_id,
                       COALESCE(container.template_id, 'other') AS template_id,
                       entity.name,
                       COALESCE(template.container_type, 'other') AS container_type,
                       entity.description,
                       COALESCE(container.has_lock, 0) AS has_lock,
                       COALESCE(container.is_locked, 0) AS is_locked,
                       COALESCE(container.is_broken, 0) AS is_broken,
                       container.unlock_difficulty,
                       COALESCE(container.hidden, 0) AS hidden,
                       container.discovery_difficulty,
                       COALESCE(container.is_open, 0) AS is_open,
                       COALESCE(container.searched, 0) AS searched
                FROM world_entities AS entity
                LEFT JOIN world_containers AS container
                  ON container.entity_id = entity.id
                LEFT JOIN container_templates AS template
                  ON template.id = container.template_id
                WHERE entity.room_id = ? AND entity.kind = 'container'
                ORDER BY entity.name COLLATE NOCASE, entity.id
                """,
                (room_id,),
            ).fetchall()
        return tuple(self._container_instance_from_row(row) for row in rows)

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
        from .room_features import RoomFeature

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
        from .room_features import RoomFeature, RoomFeatureType

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
        from .room_features import RoomFeature, RoomFeatureType

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
        from .room_features import RoomFeatureTemplate

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
        from .room_features import RoomFeatureTemplate, RoomFeatureType

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
        from .room_features import RoomFeatureTemplate, RoomFeatureType

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

    def update_container_instance(self, container):
        clean_name = self._clean_name(container.name, "Container name")
        from .locks import validate_lock

        unlock_difficulty = validate_lock(
            container.has_lock,
            container.is_locked,
            container.is_broken,
            container.unlock_difficulty,
            subject="container",
        )
        if container.is_open and container.is_locked:
            raise ValueError("A locked container cannot be open.")
        discovery_difficulty = self._validate_container_discovery(
            container.hidden,
            container.discovery_difficulty,
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container.id,),
            ).fetchone()
            if existing is None:
                raise NotFoundError(
                    f"Container '{container.id}' does not exist."
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO world_containers (
                    entity_id, template_id, has_lock, is_locked, is_broken,
                    unlock_difficulty, hidden, discovery_difficulty,
                    is_open, searched
                ) VALUES (?, ?, 0, 0, 0, NULL, 0, NULL, 0, 0)
                """,
                (container.id, container.template_id),
            )
            connection.execute(
                """
                UPDATE world_entities
                SET name = ?, description = ?
                WHERE id = ?
                """,
                (clean_name, container.description, container.id),
            )
            connection.execute(
                """
                UPDATE world_containers
                SET template_id = ?, has_lock = ?, is_locked = ?,
                    is_broken = ?, unlock_difficulty = ?, hidden = ?,
                    discovery_difficulty = ?, is_open = ?, searched = ?
                WHERE entity_id = ?
                """,
                (
                    container.template_id,
                    int(container.has_lock),
                    int(container.is_locked),
                    int(container.is_broken),
                    unlock_difficulty,
                    int(container.hidden),
                    discovery_difficulty,
                    int(container.is_open),
                    int(container.searched),
                    container.id,
                ),
            )
        updated = self.get_container_instance(container.id)
        assert updated is not None
        return updated

    def remove_container_instance(self, container_id: str) -> None:
        with self._connect() as connection:
            exists = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container_id,),
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"Container '{container_id}' does not exist.")
            connection.execute(
                "DELETE FROM character_known_containers WHERE container_id = ?",
                (container_id,),
            )
            connection.execute(
                """
                DELETE FROM inventory_stacks
                WHERE holder_kind = 'entity' AND holder_id = ?
                """,
                (container_id,),
            )
            connection.execute(
                "DELETE FROM world_containers WHERE entity_id = ?",
                (container_id,),
            )
            connection.execute(
                "DELETE FROM world_entities WHERE id = ?",
                (container_id,),
            )

    def set_world_item_quantity(
        self,
        holder: InventoryHolder,
        item_id: str,
        quantity: int,
    ) -> ItemStack:
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            item = self._require_item(connection, item_id)
            if not item.stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")
            cursor = connection.execute(
                """
                UPDATE inventory_stacks SET quantity = ?
                WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                """,
                (quantity, holder.kind.value, holder.id, item.id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Item '{item_id}' does not exist in that inventory."
                )
        return ItemStack(item, quantity)

    def character_knows_container(
        self,
        character_id: int,
        container_id: str,
    ) -> bool:
        container = self.get_container_instance(container_id)
        if container is None:
            raise NotFoundError(f"Container '{container_id}' does not exist.")
        if not container.hidden:
            return True
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT 1 FROM character_known_containers
                WHERE character_id = ? AND container_id = ?
                """,
                (character_id, container_id),
            ).fetchone() is not None

    def mark_container_discovered(
        self,
        character_id: int,
        container_id: str,
    ) -> None:
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT 1 FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            container = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'container'
                """,
                (container_id,),
            ).fetchone()
            if container is None:
                raise NotFoundError(
                    f"Container '{container_id}' does not exist."
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO character_known_containers (
                    character_id, container_id
                ) VALUES (?, ?)
                """,
                (character_id, container_id),
            )

    @staticmethod
    def _validate_container_discovery(
        hidden: bool,
        discovery_difficulty: int | None,
    ) -> int | None:
        if not hidden:
            return None
        if (
            isinstance(discovery_difficulty, bool)
            or not isinstance(discovery_difficulty, int)
            or not 1 <= discovery_difficulty <= 30
        ):
            raise ValueError(
                "Discovery difficulty must be an integer from 1 to 30."
            )
        return discovery_difficulty

    @staticmethod
    def _container_instance_from_row(row):
        from .containers import ContainerInstance, ContainerType

        return ContainerInstance(
            row["id"],
            row["room_id"],
            row["template_id"],
            row["name"],
            ContainerType(row["container_type"]),
            row["description"],
            bool(row["has_lock"]),
            bool(row["is_locked"]),
            bool(row["is_broken"]),
            row["unlock_difficulty"],
            bool(row["hidden"]),
            row["discovery_difficulty"],
            bool(row["is_open"]),
            bool(row["searched"]),
        )

    def create_character(
        self,
        discord_user_id: int,
        name: str,
        max_hp: int,
        *,
        lineage: str | None = None,
        race: str | None = None,
        age: str | None = None,
        gender: str | None = None,
        attributes: Mapping[str, int] | None = None,
        skills: Mapping[str, int] | None = None,
        portrait_key: str | None = None,
    ) -> Character:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Character name cannot be empty.")
        if len(clean_name) > 100:
            raise ValueError("Character name cannot be longer than 100 characters.")
        if max_hp <= 0:
            raise InvalidHitPointsError("Maximum HP must be greater than 0.")
        if portrait_key is None:
            portrait_key = default_portrait_key(race, gender)

        try:
            with self._connect() as connection:
                previous = connection.execute(
                    """
                    SELECT id FROM characters
                    WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                    """,
                    (discord_user_id,),
                ).fetchone()
                connection.execute(
                    """
                    UPDATE characters SET is_active = 0
                    WHERE discord_user_id = ? AND is_archived = 0
                    """,
                    (discord_user_id,),
                )
                cursor = connection.execute(
                    """
                    INSERT INTO characters (
                        discord_user_id, name, hp, max_hp, stance,
                        lineage, race, age, gender,
                        strength, dexterity, arcana, vitality, insight, personality,
                        portrait_key, is_active, is_archived
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (
                        discord_user_id,
                        clean_name,
                        max_hp,
                        max_hp,
                        Stance.STEADY.value,
                        lineage,
                        race,
                        age,
                        gender,
                        *((attributes or {}).get(attribute) for attribute in (
                            "Strength",
                            "Dexterity",
                            "Arcana",
                            "Vitality",
                            "Insight",
                            "Personality",
                        )),
                        portrait_key,
                    ),
                )
                character_id = cursor.lastrowid
                connection.execute(
                    """
                    INSERT INTO character_combat_states (
                        character_id, status, failed_death_saves
                    ) VALUES (?, 'active', 0)
                    """,
                    (character_id,),
                )
                if previous is not None:
                    self._transfer_private_views(
                        connection, previous["id"], character_id
                    )
                else:
                    self._claim_private_views(
                        connection, discord_user_id, character_id
                    )
                connection.executemany(
                    """
                    INSERT INTO character_skills (character_id, skill, rank)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (character_id, skill, rank)
                        for skill, rank in (skills or {}).items()
                    ),
                )
                self._ensure_default_clothing(connection, character_id)
        except sqlite3.IntegrityError as error:
            raise CharacterAlreadyExistsError(
                "You already have a selectable character with that name."
            ) from error

        character = self.get_character_by_id(discord_user_id, character_id)
        if character is None:
            raise RuntimeError("Newly created character could not be loaded.")
        return character

    def get_character(self, discord_user_id: int) -> Character | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (discord_user_id,),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def get_character_by_id(
        self,
        discord_user_id: int,
        character_id: int,
        *,
        include_archived: bool = False,
    ) -> Character | None:
        archived_clause = "" if include_archived else "AND is_archived = 0"
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND id = ? {archived_clause}
                """,
                (discord_user_id, character_id),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def list_characters(self, discord_user_id: int) -> list[Character]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE discord_user_id = ? AND is_archived = 0
                ORDER BY is_active DESC, id ASC
                """,
                (discord_user_id,),
            ).fetchall()
            return [self._to_character_with_skills(connection, row) for row in rows]

    def list_all_characters(self) -> list[Character]:
        """Return every selectable character for DM-facing world tools."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE is_archived = 0
                ORDER BY name COLLATE NOCASE, id ASC
                """
            ).fetchall()
            return [self._to_character_with_skills(connection, row) for row in rows]

    def get_character_by_global_id(self, character_id: int) -> Character | None:
        """Return one selectable character without requiring its Discord owner id."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            return self._to_character_with_skills(connection, row) if row else None

    def select_character(self, discord_user_id: int, character_id: int) -> Character:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM characters
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (character_id, discord_user_id),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character is not selectable.")
            previous = connection.execute(
                """
                SELECT id FROM characters
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (discord_user_id,),
            ).fetchone()
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE discord_user_id = ?",
                (discord_user_id,),
            )
            connection.execute(
                "UPDATE characters SET is_active = 1 WHERE id = ?",
                (character_id,),
            )
            if previous is not None and previous["id"] != character_id:
                self._transfer_private_views(
                    connection, previous["id"], character_id
                )
            elif previous is None:
                self._claim_private_views(
                    connection, discord_user_id, character_id
                )
        character = self.get_character(discord_user_id)
        if character is None:
            raise RuntimeError("Selected character could not be loaded.")
        return character

    @staticmethod
    def _transfer_private_views(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        """Move player-owned Discord HUD bindings while preserving knowledge."""
        Database._transfer_map_view(
            connection, previous_character_id, new_character_id
        )
        Database._transfer_sheet_view(
            connection, previous_character_id, new_character_id
        )

    @staticmethod
    def _claim_private_views(
        connection: sqlite3.Connection,
        discord_user_id: int,
        new_character_id: int,
    ) -> None:
        map_owner = connection.execute(
            """
            SELECT state.character_id FROM player_view_states AS state
            JOIN characters ON characters.id = state.character_id
            WHERE characters.discord_user_id = ? AND state.character_id != ?
            ORDER BY state.character_id DESC LIMIT 1
            """,
            (discord_user_id, new_character_id),
        ).fetchone()
        if map_owner is not None:
            Database._transfer_map_view(
                connection, map_owner["character_id"], new_character_id
            )
        sheet_owner = connection.execute(
            """
            SELECT state.character_id FROM character_sheet_view_states AS state
            JOIN characters ON characters.id = state.character_id
            WHERE characters.discord_user_id = ? AND state.character_id != ?
            ORDER BY state.character_id DESC LIMIT 1
            """,
            (discord_user_id, new_character_id),
        ).fetchone()
        if sheet_owner is not None:
            Database._transfer_sheet_view(
                connection, sheet_owner["character_id"], new_character_id
            )

    @staticmethod
    def _transfer_map_view(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        previous_map = connection.execute(
            "SELECT * FROM player_view_states WHERE character_id = ?",
            (previous_character_id,),
        ).fetchone()
        if previous_map is not None:
            connection.execute(
                "DELETE FROM player_view_states WHERE character_id = ?",
                (new_character_id,),
            )
            room = connection.execute(
                """
                SELECT rooms.id, rooms.floor_id FROM characters
                LEFT JOIN rooms ON rooms.id = characters.current_room_id
                WHERE characters.id = ?
                """,
                (new_character_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE player_view_states
                SET character_id = ?, selected_floor_id = ?, focused_room_id = ?
                WHERE character_id = ?
                """,
                (
                    new_character_id,
                    room["floor_id"] if room else None,
                    room["id"] if room else None,
                    previous_character_id,
                ),
            )

    @staticmethod
    def _transfer_sheet_view(
        connection: sqlite3.Connection,
        previous_character_id: int,
        new_character_id: int,
    ) -> None:
        previous_sheet = connection.execute(
            "SELECT 1 FROM character_sheet_view_states WHERE character_id = ?",
            (previous_character_id,),
        ).fetchone()
        if previous_sheet is not None:
            connection.execute(
                "DELETE FROM character_sheet_view_states WHERE character_id = ?",
                (new_character_id,),
            )
            connection.execute(
                """
                UPDATE character_sheet_view_states SET character_id = ?
                WHERE character_id = ?
                """,
                (new_character_id, previous_character_id),
            )

    def deactivate_character(self, discord_user_id: int) -> None:
        """Leave a Discord user without an equipped/active character."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE characters SET is_active = 0
                WHERE discord_user_id = ? AND is_archived = 0
                """,
                (discord_user_id,),
            )

    def get_character_sheet_message(
        self, guild_id: int, channel_id: int, character_id: int
    ) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT message_id FROM character_sheet_messages
                WHERE guild_id = ? AND channel_id = ? AND character_id = ?
                """,
                (guild_id, channel_id, character_id),
            ).fetchone()
        return row["message_id"] if row else None

    def set_character_sheet_message(
        self,
        guild_id: int,
        channel_id: int,
        character_id: int,
        message_id: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_sheet_messages (
                    guild_id, channel_id, character_id, message_id
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (guild_id, channel_id, character_id)
                DO UPDATE SET message_id = excluded.message_id
                """,
                (guild_id, channel_id, character_id, message_id),
            )

    def get_character_sheet_view_state(
        self, character_id: int
    ) -> CharacterSheetViewState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT character_id, guild_id, discord_channel_id, discord_message_id
                FROM character_sheet_view_states WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()
        if row is None:
            return None
        return CharacterSheetViewState(
            row["character_id"], row["guild_id"], row["discord_channel_id"],
            row["discord_message_id"],
        )

    def bind_character_sheet_channel(
        self, character_id: int, guild_id: int, channel_id: int
    ) -> CharacterSheetViewState:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO character_sheet_view_states (
                    character_id, guild_id, discord_channel_id, discord_message_id
                ) VALUES (?, ?, ?, NULL)
                ON CONFLICT(character_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    discord_channel_id = excluded.discord_channel_id,
                    discord_message_id = CASE
                        WHEN character_sheet_view_states.guild_id = excluded.guild_id
                         AND character_sheet_view_states.discord_channel_id = excluded.discord_channel_id
                        THEN character_sheet_view_states.discord_message_id
                        ELSE NULL
                    END
                """,
                (character_id, guild_id, channel_id),
            )
        state = self.get_character_sheet_view_state(character_id)
        assert state is not None
        return state

    def set_character_sheet_view_message(
        self, character_id: int, message_id: int
    ) -> CharacterSheetViewState:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE character_sheet_view_states SET discord_message_id = ?
                WHERE character_id = ?
                """,
                (message_id, character_id),
            )
            if cursor.rowcount == 0:
                raise ValueError("The character sheet channel is not configured.")
        state = self.get_character_sheet_view_state(character_id)
        assert state is not None
        return state

    def clear_character_sheet_view_state(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM character_sheet_view_states WHERE character_id = ?",
                (character_id,),
            )

    def list_character_sheet_view_states(
        self,
    ) -> tuple[CharacterSheetViewState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id, guild_id, discord_channel_id, discord_message_id
                FROM character_sheet_view_states ORDER BY character_id
                """
            ).fetchall()
        return tuple(
            CharacterSheetViewState(
                row["character_id"], row["guild_id"], row["discord_channel_id"],
                row["discord_message_id"],
            )
            for row in rows
        )

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

    def update_character_admin(
        self,
        character_id: int,
        *,
        name: str,
        hp: int,
        max_hp: int,
        stance: Stance,
        lineage: str | None,
        race: str | None,
        age: str | None,
        gender: str | None,
        attributes: Mapping[str, int],
        skills: Mapping[str, int],
        status: CharacterCombatStatus,
        failed_death_saves: int,
        current_room_id: str | None,
        copper: int,
        silver: int,
        gold: int,
    ) -> Character:
        """Apply an explicit DM edit to a character and its attached state."""
        clean_name = self._clean_name(name, "Character name")
        if max_hp <= 0:
            raise InvalidHitPointsError("Maximum HP must be greater than 0.")
        if not -max_hp <= hp <= max_hp:
            raise InvalidHitPointsError(
                f"HP must be between {-max_hp} and {max_hp}."
            )
        if not 0 <= failed_death_saves <= 3:
            raise ValueError("Failed death saves must be between 0 and 3.")
        if copper < 0 or silver < 0 or gold < 0:
            raise ValueError("Currency amounts cannot be negative.")

        attribute_names = (
            "Strength",
            "Dexterity",
            "Arcana",
            "Vitality",
            "Insight",
            "Personality",
        )
        normalized_attributes: dict[str, int | None] = {}
        for attribute in attribute_names:
            value = attributes.get(attribute)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise ValueError(f"{attribute} must be an integer.")
            normalized_attributes[attribute] = value

        normalized_skills: dict[str, int] = {}
        for skill, rank in skills.items():
            clean_skill = skill.strip()
            if not clean_skill:
                raise ValueError("Skill names cannot be empty.")
            if len(clean_skill) > 100:
                raise ValueError("Skill names cannot be longer than 100 characters.")
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
                raise ValueError("Skill ranks must be non-negative integers.")
            if rank:
                normalized_skills[clean_skill] = rank

        with self._connect() as connection:
            current = connection.execute(
                """
                SELECT current_room_id FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if current is None:
                raise CharacterNotFoundError("That character does not exist.")
            if current_room_id is not None:
                self._require_room(connection, current_room_id)

            try:
                connection.execute(
                    """
                    UPDATE characters
                    SET name = ?, hp = ?, max_hp = ?, stance = ?,
                        lineage = ?, race = ?, age = ?, gender = ?,
                        strength = ?, dexterity = ?, arcana = ?,
                        vitality = ?, insight = ?, personality = ?,
                        current_room_id = ?
                    WHERE id = ? AND is_archived = 0
                    """,
                    (
                        clean_name,
                        hp,
                        max_hp,
                        stance.value,
                        lineage,
                        race,
                        age,
                        gender,
                        normalized_attributes["Strength"],
                        normalized_attributes["Dexterity"],
                        normalized_attributes["Arcana"],
                        normalized_attributes["Vitality"],
                        normalized_attributes["Insight"],
                        normalized_attributes["Personality"],
                        current_room_id,
                        character_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise CharacterAlreadyExistsError(
                    "That Discord user already has a selectable character with this name."
                ) from error

            connection.execute(
                "DELETE FROM character_skills WHERE character_id = ?",
                (character_id,),
            )
            connection.executemany(
                """
                INSERT INTO character_skills (character_id, skill, rank)
                VALUES (?, ?, ?)
                """,
                (
                    (character_id, skill, rank)
                    for skill, rank in normalized_skills.items()
                ),
            )

            self._ensure_character_combat_state_row(connection, character_id)
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (status.value, failed_death_saves, character_id),
            )

            connection.execute(
                "INSERT OR IGNORE INTO character_wallets (character_id) VALUES (?)",
                (character_id,),
            )
            connection.execute(
                """
                UPDATE character_wallets
                SET copper = ?, silver = ?, gold = ?
                WHERE character_id = ?
                """,
                (copper, silver, gold, character_id),
            )

            previous_room_id = current["current_room_id"]
            if previous_room_id != current_room_id:
                if previous_room_id is not None:
                    self._queue_map_refresh_for_room(
                        connection,
                        previous_room_id,
                    )
                if current_room_id is not None:
                    self._record_room_visit(
                        connection,
                        character_id,
                        current_room_id,
                    )
                    self._queue_map_refresh_for_room(
                        connection,
                        current_room_id,
                    )

        updated = self.get_character_by_global_id(character_id)
        if updated is None:
            raise RuntimeError("Updated character could not be loaded.")
        return updated

    def set_character_inventory_item_admin(
        self,
        character_id: int,
        instance_id: str,
        *,
        quantity: int,
        durability: int | None,
        equipped_slot: EquipmentSlot | None,
    ) -> None:
        """Update one inventory instance from the local DM workspace."""
        if durability is not None and durability < 0:
            raise ValueError("Durability cannot be negative.")
        with self._connect() as connection:
            item = connection.execute(
                """
                SELECT 1 FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            ).fetchone()
            if item is None:
                raise ValueError("That item is not in this inventory.")

            connection.execute(
                """
                DELETE FROM character_equipment
                WHERE character_id = ? AND item_instance_id = ?
                """,
                (character_id, instance_id),
            )
            if quantity <= 0:
                connection.execute(
                    """
                    DELETE FROM character_items
                    WHERE character_id = ? AND instance_id = ?
                    """,
                    (character_id, instance_id),
                )
                return

            connection.execute(
                """
                UPDATE character_items
                SET quantity = ?, durability = ?, parent_container_id = NULL
                WHERE character_id = ? AND instance_id = ?
                """,
                (quantity, durability, character_id, instance_id),
            )
            if equipped_slot is not None:
                connection.execute(
                    """
                    DELETE FROM character_equipment
                    WHERE character_id = ? AND slot = ?
                    """,
                    (character_id, equipped_slot.value),
                )
                connection.execute(
                    """
                    INSERT INTO character_equipment (
                        character_id, slot, item_instance_id
                    ) VALUES (?, ?, ?)
                    """,
                    (character_id, equipped_slot.value, instance_id),
                )

    def set_character_portrait(
        self, discord_user_id: int, character_id: int, portrait_key: str | None
    ) -> Character:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE characters SET portrait_key = ?
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (portrait_key, character_id, discord_user_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That character is not selectable.")
        character = self.get_character_by_id(discord_user_id, character_id)
        if character is None:
            raise RuntimeError("Updated character could not be loaded.")
        return character

    def archive_character(self, discord_user_id: int, character_id: int) -> Character:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, is_active FROM characters
                WHERE id = ? AND discord_user_id = ? AND is_archived = 0
                """,
                (character_id, discord_user_id),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character is not selectable.")
            connection.execute(
                "UPDATE characters SET is_active = 0, is_archived = 1 WHERE id = ?",
                (character_id,),
            )
            if row["is_active"]:
                replacement = connection.execute(
                    """
                    SELECT id FROM characters
                    WHERE discord_user_id = ? AND is_archived = 0
                    ORDER BY id DESC LIMIT 1
                    """,
                    (discord_user_id,),
                ).fetchone()
                if replacement is not None:
                    connection.execute(
                        "UPDATE characters SET is_active = 1 WHERE id = ?",
                        (replacement["id"],),
                    )
                    self._transfer_private_views(
                        connection, character_id, replacement["id"]
                    )
        archived = self.get_character_by_id(
            discord_user_id, character_id, include_archived=True
        )
        if archived is None:
            raise RuntimeError("Archived character could not be loaded.")
        return archived

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

    def create_room(
        self,
        room_id: str,
        area_id: str,
        name: str,
        description: str | None = None,
        *,
        floor_id: str | None = None,
        width: float = 1.0,
        height: float = 1.0,
        scene_image_path: str | None = None,
        scene_image_url: str | None = None,
        scene_prompt: str | None = None,
    ) -> Room:
        room_id = self._clean_identifier(room_id, "Room ID")
        name = self._clean_name(name, "Room name")
        with self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM areas WHERE id = ?", (area_id,)
            ).fetchone():
                raise NotFoundError(f"Area '{area_id}' does not exist.")
            floor_id = floor_id or f"{area_id}:floor:1"
            floor = connection.execute(
                "SELECT dungeon_id FROM dungeon_floors WHERE id = ?", (floor_id,)
            ).fetchone()
            if floor is None or floor["dungeon_id"] != area_id:
                raise NotFoundError(
                    f"Floor '{floor_id}' does not exist in dungeon '{area_id}'."
                )
            width = self._validate_room_dimension(width, "width")
            height = self._validate_room_dimension(height, "height")
            try:
                connection.execute(
                    """
                    INSERT INTO rooms (
                        id, area_id, name, description, floor_id, width, height,
                        scene_image_path, scene_image_url, scene_prompt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        room_id, area_id, name, description, floor_id, width, height,
                        scene_image_path, scene_image_url, scene_prompt,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Room '{room_id}' already exists.") from error
        room = self.get_room(room_id)
        assert room is not None
        return room

    def connect_rooms(
        self,
        room_id: str,
        exit_name: str,
        destination_room_id: str,
        *,
        return_exit_name: str | None = None,
        connection_type: ConnectionType = ConnectionType.PASSAGE,
        hidden: bool = False,
        has_lock: bool = False,
        is_locked: bool = False,
        unlock_difficulty: int | None = None,
        is_broken: bool = False,
        is_open: bool = False,
        has_trap: bool = False,
        trap_state: TrapState | None = None,
        trap_detection_difficulty: int | None = None,
        trap_disarm_difficulty: int | None = None,
        trap_damage_type: TrapDamageType | None = None,
        trap_damage: int | None = None,
    ) -> RoomConnection:
        exit_name = self._clean_name(exit_name, "Exit name")
        if return_exit_name is not None:
            return_exit_name = self._clean_name(return_exit_name, "Return exit name")
        unlock_difficulty = self._validate_connection_lock(
            connection_type, has_lock, is_locked, is_broken, unlock_difficulty
        )
        self._validate_connection_open(connection_type, is_open, is_locked)
        trap_state, trap_detection_difficulty, trap_damage_type, trap_damage = (
            self._validate_connection_trap(
                connection_type,
                has_trap,
                trap_state,
                trap_detection_difficulty,
                trap_damage_type,
                trap_damage,
            )
        )
        if has_trap:
            trap_disarm_difficulty = trap_disarm_difficulty or 10
            if not 1 <= trap_disarm_difficulty <= 30:
                raise ValueError(
                    "Trap disarm difficulty must be an integer from 1 to 30."
                )
        else:
            trap_disarm_difficulty = None
        with self._connect() as connection:
            source_room = self._require_room(connection, room_id)
            destination_room = self._require_room(connection, destination_room_id)
            if source_room["area_id"] != destination_room["area_id"]:
                raise InvalidMovementError("Rooms in different areas cannot be connected.")
            duplicate_destination = connection.execute(
                """
                SELECT 1 FROM room_exits
                WHERE room_id = ? AND destination_room_id = ?
                """,
                (room_id, destination_room_id),
            ).fetchone()
            if duplicate_destination:
                raise InvalidMovementError("Those rooms are already connected.")
            duplicate_name = connection.execute(
                """
                SELECT 1 FROM room_exits
                WHERE room_id = ? AND name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if duplicate_name:
                raise InvalidMovementError(
                    f"This room already has an exit named '{exit_name}'. "
                    "Choose a different exit name."
                )
            if return_exit_name is not None:
                reverse_destination = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND destination_room_id = ?
                    """,
                    (destination_room_id, room_id),
                ).fetchone()
                if reverse_destination:
                    raise InvalidMovementError("Those rooms are already connected.")
                reverse_name = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                    """,
                    (destination_room_id, return_exit_name),
                ).fetchone()
                if reverse_name:
                    raise InvalidMovementError(
                        f"The destination already has an exit named "
                        f"'{return_exit_name}'. Choose a different return exit name."
                    )
            connection.execute(
                """
                INSERT INTO room_exits (room_id, name, destination_room_id)
                VALUES (?, ?, ?)
                """,
                (room_id, exit_name, destination_room_id),
            )
            if return_exit_name is not None:
                connection.execute(
                    """
                    INSERT INTO room_exits (room_id, name, destination_room_id)
                    VALUES (?, ?, ?)
                    """,
                    (destination_room_id, return_exit_name, room_id),
                )
            connection_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO room_connections (
                    id, from_room_id, to_room_id, exit_name, return_exit_name,
                    connection_type, hidden, bidirectional, is_locked,
                    is_broken, is_open, unlock_difficulty, has_lock, has_trap,
                    trap_state, trap_detection_difficulty,
                    trap_disarm_difficulty, trap_damage_type, trap_damage
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    room_id,
                    destination_room_id,
                    exit_name,
                    return_exit_name,
                    connection_type.value,
                    int(hidden),
                    int(return_exit_name is not None),
                    int(is_locked),
                    int(is_broken),
                    int(is_open),
                    unlock_difficulty,
                    int(has_lock),
                    int(has_trap),
                    trap_state.value if trap_state is not None else None,
                    trap_detection_difficulty,
                    trap_disarm_difficulty,
                    trap_damage_type.value if trap_damage_type is not None else None,
                    trap_damage,
                ),
            )
            if not hidden:
                visible_endpoints = [room_id]
                if return_exit_name is not None:
                    visible_endpoints.append(destination_room_id)
                placeholders = ", ".join("?" for _ in visible_endpoints)
                present_characters = connection.execute(
                    f"""
                    SELECT id, current_room_id
                    FROM characters
                    WHERE is_archived = 0
                      AND current_room_id IN ({placeholders})
                    """,
                    visible_endpoints,
                ).fetchall()
                for character_row in present_characters:
                    character_id = character_row["id"]
                    current_room_id = character_row["current_room_id"]
                    adjacent_room_id = (
                        destination_room_id
                        if current_room_id == room_id
                        else room_id
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO character_known_connections (
                            character_id, connection_id
                        ) VALUES (?, ?)
                        """,
                        (character_id, connection_id),
                    )
                    if connection_type is ConnectionType.DOOR and not is_open:
                        continue
                    connection.execute(
                        """
                        INSERT INTO character_room_knowledge (
                            character_id, room_id, state, source
                        ) VALUES (?, ?, 'known', 'discovered')
                        ON CONFLICT(character_id, room_id) DO NOTHING
                        """,
                        (character_id, adjacent_room_id),
                    )
                for endpoint_room_id in visible_endpoints:
                    self._queue_map_refresh_for_room(connection, endpoint_room_id)
        return RoomConnection(
            connection_id,
            room_id,
            destination_room_id,
            connection_type,
            hidden,
            return_exit_name is not None,
            has_lock,
            is_locked,
            unlock_difficulty,
            is_broken,
            is_open,
            has_trap,
            trap_state,
            trap_detection_difficulty,
            trap_disarm_difficulty,
            trap_damage_type,
            trap_damage,
        )

    def disconnect_rooms(self, room_id: str, exit_name: str) -> None:
        """Backward-compatible alias for removing a complete passage."""
        self.disconnect_connection(room_id, exit_name)

    def set_connection_direction(
        self,
        room_id: str,
        exit_name: str,
        *,
        bidirectional: bool,
        return_exit_name: str | None = None,
    ) -> None:
        """Change a canonical connection between one-way and two-way."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, exit_name,
                       return_exit_name, bidirectional
                FROM room_connections
                WHERE from_room_id = ? AND exit_name = ? COLLATE NOCASE
                """,
                (room_id, exit_name),
            ).fetchone()
            if row is None:
                raise NotFoundError(
                    f"Connection '{exit_name}' does not exist on room '{room_id}'."
                )

            if row["bidirectional"] and row["return_exit_name"]:
                connection.execute(
                    """
                    DELETE FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                      AND destination_room_id = ?
                    """,
                    (
                        row["to_room_id"],
                        row["return_exit_name"],
                        row["from_room_id"],
                    ),
                )

            clean_return_name = None
            if bidirectional:
                clean_return_name = self._clean_name(
                    return_exit_name or row["exit_name"], "Return exit name"
                )
                conflict = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND (
                        name = ? COLLATE NOCASE OR destination_room_id = ?
                    )
                    """,
                    (
                        row["to_room_id"],
                        clean_return_name,
                        row["from_room_id"],
                    ),
                ).fetchone()
                if conflict is not None:
                    raise InvalidMovementError(
                        "That return connection conflicts with an existing exit."
                    )
                connection.execute(
                    """
                    INSERT INTO room_exits (room_id, name, destination_room_id)
                    VALUES (?, ?, ?)
                    """,
                    (
                        row["to_room_id"],
                        clean_return_name,
                        row["from_room_id"],
                    ),
                )

            connection.execute(
                """
                UPDATE room_connections
                SET return_exit_name = ?, bidirectional = ?
                WHERE id = ?
                """,
                (clean_return_name, int(bidirectional), row["id"]),
            )

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
        from .locks import validate_lock

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

    def disconnect_connection(self, room_id: str, exit_name: str) -> None:
        """Remove a canonical connection and both exits when applicable."""
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, from_room_id, to_room_id, exit_name,
                       return_exit_name, bidirectional
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
                """
                DELETE FROM room_exits
                WHERE room_id = ? AND name = ? COLLATE NOCASE
                  AND destination_room_id = ?
                """,
                (row["from_room_id"], row["exit_name"], row["to_room_id"]),
            )
            if row["bidirectional"] and row["return_exit_name"]:
                connection.execute(
                    """
                    DELETE FROM room_exits
                    WHERE room_id = ? AND name = ? COLLATE NOCASE
                      AND destination_room_id = ?
                    """,
                    (
                        row["to_room_id"],
                        row["return_exit_name"],
                        row["from_room_id"],
                    ),
                )
            connection.execute(
                "DELETE FROM character_known_connections WHERE connection_id = ?",
                (row["id"],),
            )
            connection.execute(
                "DELETE FROM room_connections WHERE id = ?", (row["id"],)
            )

    def update_room(
        self, room_id: str, name: str, description: str | None = None
    ) -> Room:
        name = self._clean_name(name, "Room name")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE rooms SET name = ?, description = ? WHERE id = ?",
                (name, description, room_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Room '{room_id}' does not exist.")
        room = self.get_room(room_id)
        assert room is not None
        return room

    def delete_room(self, room_id: str) -> None:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            occupied = connection.execute(
                "SELECT 1 FROM characters WHERE current_room_id = ? LIMIT 1", (room_id,)
            ).fetchone()
            entities = connection.execute(
                "SELECT 1 FROM world_entities WHERE room_id = ? LIMIT 1", (room_id,)
            ).fetchone()
            items = connection.execute(
                """
                SELECT 1 FROM inventory_stacks
                WHERE holder_kind = 'room' AND holder_id = ? LIMIT 1
                """,
                (room_id,),
            ).fetchone()
            if occupied or entities or items:
                raise ValueError(
                    "Move characters, entities, and loose items before deleting this room."
                )
            connection.execute(
                "DELETE FROM room_exits WHERE room_id = ? OR destination_room_id = ?",
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM character_room_knowledge WHERE room_id = ?", (room_id,)
            )
            connection.execute(
                "UPDATE player_view_states SET focused_room_id = NULL WHERE focused_room_id = ?",
                (room_id,),
            )
            connection.execute(
                """
                DELETE FROM character_known_connections
                WHERE connection_id IN (
                    SELECT id FROM room_connections
                    WHERE from_room_id = ? OR to_room_id = ?
                )
                """,
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM room_connections WHERE from_room_id = ? OR to_room_id = ?",
                (room_id, room_id),
            )
            connection.execute(
                "DELETE FROM room_editor_metadata WHERE room_id = ?", (room_id,)
            )
            connection.execute("DELETE FROM rooms WHERE id = ?", (room_id,))

    def set_room_editor_position(self, room_id: str, x: float, y: float) -> None:
        x = self._validate_editor_coordinate(x, "x")
        y = self._validate_editor_coordinate(y, "y")
        with self._connect() as connection:
            self._require_room(connection, room_id)
            connection.execute(
                """
                INSERT INTO room_editor_metadata (room_id, x, y) VALUES (?, ?, ?)
                ON CONFLICT(room_id) DO UPDATE SET x = excluded.x, y = excluded.y
                """,
                (room_id, x, y),
            )

    def get_area_graph(self, area_id: str) -> AreaGraph:
        area = self.get_area(area_id)
        if area is None:
            raise NotFoundError(f"Area '{area_id}' does not exist.")
        with self._connect() as connection:
            nodes = []
            connections = []
            for index, room_id in enumerate(area.room_ids):
                room_row = self._require_room(connection, room_id)
                room = self._to_room(connection, room_row)
                position = connection.execute(
                    "SELECT x, y FROM room_editor_metadata WHERE room_id = ?",
                    (room_id,),
                ).fetchone()
                x = position["x"] if position else 120.0 + (index % 3) * 300.0
                y = position["y"] if position else 100.0 + (index // 3) * 220.0
                nodes.append(RoomEditorNode(room, x, y))
            connection_rows = connection.execute(
                """
                SELECT links.id, links.from_room_id, links.exit_name,
                       links.to_room_id, links.return_exit_name,
                       links.bidirectional, links.hidden, links.connection_type,
                       links.has_lock, links.is_locked, links.unlock_difficulty,
                       links.is_broken, links.is_open,
                       links.has_trap, links.trap_state,
                       links.trap_detection_difficulty, links.trap_disarm_difficulty,
                       links.trap_damage_type, links.trap_damage
                FROM room_connections AS links
                JOIN rooms AS source ON source.id = links.from_room_id
                WHERE source.area_id = ?
                ORDER BY source.name COLLATE NOCASE, links.exit_name COLLATE NOCASE
                """,
                (area_id,),
            ).fetchall()
            connections = [
                GraphConnection(
                    row["from_room_id"],
                    row["exit_name"],
                    row["to_room_id"],
                    row["id"],
                    row["return_exit_name"],
                    bool(row["bidirectional"]),
                    bool(row["hidden"]),
                    ConnectionType(row["connection_type"]),
                    bool(row["has_lock"]),
                    bool(row["is_locked"]),
                    row["unlock_difficulty"],
                    bool(row["is_broken"]),
                    bool(row["is_open"]),
                    bool(row["has_trap"]),
                    (
                        TrapState(row["trap_state"])
                        if row["trap_state"] is not None
                        else None
                    ),
                    row["trap_detection_difficulty"],
                    row["trap_disarm_difficulty"],
                    (
                        TrapDamageType(row["trap_damage_type"])
                        if row["trap_damage_type"] is not None
                        else None
                    ),
                    row["trap_damage"],
                )
                for row in connection_rows
            ]
        return AreaGraph(area, tuple(nodes), tuple(connections))

    def get_room(self, room_id: str) -> Room | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, area_id, name, description, floor_id, width, height,
                       scene_image_path, scene_image_url, scene_prompt
                FROM rooms WHERE id = ?
                """,
                (room_id,),
            ).fetchone()
            return self._to_room(connection, row) if row else None

    def get_character_room(self, character_id: int) -> Room | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if row is None:
                raise CharacterNotFoundError("That character does not exist.")
            if row["current_room_id"] is None:
                return None
            room_row = connection.execute(
                """
                SELECT id, area_id, name, description, floor_id, width, height,
                       scene_image_path, scene_image_url, scene_prompt
                FROM rooms WHERE id = ?
                """,
                (row["current_room_id"],),
            ).fetchone()
            return self._to_room(connection, room_row) if room_row else None

    def place_character(self, character_id: int, room_id: str) -> Room:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            previous = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            cursor = connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ? AND is_archived = 0",
                (room_id, character_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That character does not exist.")
            self._record_room_visit(connection, character_id, room_id)
            if previous is not None and previous["current_room_id"] is not None:
                self._queue_map_refresh_for_room(
                    connection, previous["current_room_id"]
                )
            self._queue_map_refresh_for_room(connection, room_id)
        room = self.get_room(room_id)
        assert room is not None
        return room

    def set_room_scene_image(
        self, room_id: str, scene_image_path: str | None
    ) -> Room:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            connection.execute(
                """
                UPDATE rooms
                SET scene_image_path = ?, scene_image_url = NULL
                WHERE id = ?
                """,
                (scene_image_path, room_id),
            )
            self._queue_map_refresh_for_room(
                connection, room_id, include_focused=True
            )
        room = self.get_room(room_id)
        assert room is not None
        return room

    def ensure_character_location_knowledge(self, character_id: int) -> None:
        """Ensure the current room and its presently visible exits are known."""
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT current_room_id FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            room_id = character["current_room_id"]
            if room_id is None:
                return
            known = connection.execute(
                """
                SELECT 1 FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (character_id, room_id),
            ).fetchone()
            if known is None:
                self._record_room_visit(connection, character_id, room_id)
            else:
                self._record_visible_connections(
                    connection, character_id, room_id
                )

    def move_character(self, character_id: int, destination: str) -> Room:
        return self.move_character_with_result(character_id, destination).room

    def move_character_with_result(
        self, character_id: int, destination: str
    ) -> MovementResult:
        destination = destination.strip()
        trap_triggered = False
        trap_damage = 0
        trap_damage_type = None
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT current_room_id, hp, max_hp
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            current_room_id = character["current_room_id"]
            if current_room_id is None:
                raise InvalidMovementError("The character is not currently in a room.")
            exit_row = connection.execute(
                """
                SELECT name, destination_room_id FROM room_exits
                WHERE room_id = ? AND (name = ? COLLATE NOCASE OR destination_room_id = ?)
                """,
                (current_room_id, destination, destination),
            ).fetchone()
            if exit_row is None:
                raise InvalidMovementError(
                    f"'{destination}' is not an exit from the current room."
                )
            destination_id = exit_row["destination_room_id"]
            locked = connection.execute(
                """
                SELECT id, from_room_id, to_room_id,
                       is_locked, is_open, connection_type,
                       has_trap, trap_state, trap_damage_type,
                       trap_damage
                FROM room_connections
                WHERE (
                    from_room_id = ? AND exit_name = ? COLLATE NOCASE
                    AND to_room_id = ?
                ) OR (
                    to_room_id = ? AND return_exit_name = ? COLLATE NOCASE
                    AND from_room_id = ?
                )
                """,
                (
                    current_room_id,
                    exit_row["name"],
                    destination_id,
                    current_room_id,
                    exit_row["name"],
                    destination_id,
                ),
            ).fetchone()
            if locked is not None and locked["is_locked"]:
                raise InvalidMovementError("That door is locked.")
            self._require_room(connection, destination_id)
            if (
                locked is not None
                and locked["has_trap"]
                and locked["trap_state"] == TrapState.ARMED.value
            ):
                configured_damage = max(0, int(locked["trap_damage"] or 0))
                trap_triggered = True
                trap_damage_type = (
                    TrapDamageType(locked["trap_damage_type"])
                    if locked["trap_damage_type"]
                    else None
                )
                if configured_damage:
                    new_hp, _, _ = self._apply_character_damage(
                        connection,
                        character_id,
                        configured_damage,
                    )
                    trap_damage = int(character["hp"]) - new_hp
                connection.execute(
                    "UPDATE room_connections SET trap_state = ? WHERE id = ?",
                    (TrapState.TRIGGERED.value, locked["id"]),
                )
                self._queue_map_refresh_for_room(connection, locked["from_room_id"])
                self._queue_map_refresh_for_room(connection, locked["to_room_id"])
            if (
                locked is not None
                and ConnectionType(locked["connection_type"])
                is ConnectionType.DOOR
                and not locked["is_open"]
            ):
                connection.execute(
                    "UPDATE room_connections SET is_open = 1 WHERE id = ?",
                    (locked["id"],),
                )
                self._queue_map_refresh_for_room(connection, locked["from_room_id"])
                self._queue_map_refresh_for_room(connection, locked["to_room_id"])
            connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ?",
                (destination_id, character_id),
            )
            self._record_room_visit(connection, character_id, destination_id)
            self._queue_map_refresh_for_room(connection, current_room_id)
            self._queue_map_refresh_for_room(connection, destination_id)
        room = self.get_room(destination_id)
        assert room is not None
        return MovementResult(
            room=room,
            trap_triggered=trap_triggered,
            trap_damage=trap_damage,
            trap_damage_type=trap_damage_type,
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

    def get_character_location(self, character_id: int) -> CharacterLocation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
        if row is None:
            raise CharacterNotFoundError("That character does not exist.")
        if row["current_room_id"] is None:
            return None
        return CharacterLocation(character_id, row["current_room_id"])

    def get_character_knowledge(
        self, character_id: int, room_id: str
    ) -> CharacterRoomKnowledge | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT character_id, room_id, state, source, first_visited_at,
                       last_visited_at, last_seen_scene_id, shared_by_character_id
                FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (character_id, room_id),
            ).fetchone()
            if row is None:
                return None
            connection_ids = tuple(
                item["connection_id"]
                for item in connection.execute(
                    """
                    SELECT connection_id FROM character_known_connections
                    WHERE character_id = ? ORDER BY connection_id
                    """,
                    (character_id,),
                )
                if connection.execute(
                    """
                    SELECT 1 FROM room_connections
                    WHERE id = ? AND (from_room_id = ? OR to_room_id = ?)
                    """,
                    (item["connection_id"], room_id, room_id),
                ).fetchone()
            )
            return self._to_knowledge(row, connection_ids)

    def list_character_knowledge(
        self, character_id: int, *, floor_id: str | None = None
    ) -> tuple[CharacterRoomKnowledge, ...]:
        with self._connect() as connection:
            parameters: list[object] = [character_id]
            floor_clause = ""
            if floor_id is not None:
                floor_clause = " AND rooms.floor_id = ?"
                parameters.append(floor_id)
            rows = connection.execute(
                """
                SELECT k.character_id, k.room_id, k.state, k.source,
                       k.first_visited_at, k.last_visited_at, k.last_seen_scene_id,
                       k.shared_by_character_id
                FROM character_room_knowledge AS k
                JOIN rooms ON rooms.id = k.room_id
                WHERE k.character_id = ?
                """ + floor_clause + " ORDER BY k.room_id",
                parameters,
            ).fetchall()
            known_connections = {
                item["connection_id"]
                for item in connection.execute(
                    """
                    SELECT connection_id FROM character_known_connections
                    WHERE character_id = ?
                    """,
                    (character_id,),
                )
            }
            result = []
            for row in rows:
                room_connection_ids = tuple(
                    item["id"]
                    for item in connection.execute(
                        """
                        SELECT id FROM room_connections
                        WHERE from_room_id = ? OR to_room_id = ? ORDER BY id
                        """,
                        (row["room_id"], row["room_id"]),
                    )
                    if item["id"] in known_connections
                )
                result.append(self._to_knowledge(row, room_connection_ids))
            return tuple(result)

    def share_room_knowledge(
        self, from_character_id: int, to_character_id: int, room_id: str
    ) -> CharacterRoomKnowledge:
        if from_character_id == to_character_id:
            raise ValueError("A character cannot share room knowledge with itself.")
        with self._connect() as connection:
            source = connection.execute(
                """
                SELECT 1 FROM character_room_knowledge
                WHERE character_id = ? AND room_id = ?
                """,
                (from_character_id, room_id),
            ).fetchone()
            if source is None:
                raise ValueError("The sharing character does not know that room.")
            if connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (to_character_id,),
            ).fetchone() is None:
                raise CharacterNotFoundError("The receiving character does not exist.")
            connection.execute(
                """
                INSERT INTO character_room_knowledge (
                    character_id, room_id, state, source, shared_by_character_id
                ) VALUES (?, ?, 'known', 'shared', ?)
                ON CONFLICT(character_id, room_id) DO NOTHING
                """,
                (to_character_id, room_id, from_character_id),
            )
        knowledge = self.get_character_knowledge(to_character_id, room_id)
        assert knowledge is not None
        return knowledge

    def list_known_connections(self, character_id: int) -> tuple[RoomConnection, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.from_room_id, c.to_room_id, c.connection_type,
                       c.hidden, c.bidirectional, c.has_lock, c.is_locked,
                       c.unlock_difficulty, c.is_broken, c.is_open, c.has_trap,
                       c.trap_state, c.trap_detection_difficulty,
                       c.trap_disarm_difficulty,
                       c.trap_damage_type,
                       c.trap_damage
                FROM room_connections AS c
                JOIN character_known_connections AS known
                  ON known.connection_id = c.id
                WHERE known.character_id = ? AND c.hidden = 0
                ORDER BY c.id
                """,
                (character_id,),
            ).fetchall()
        return tuple(
            RoomConnection(
                row["id"], row["from_room_id"], row["to_room_id"],
                ConnectionType(row["connection_type"]), bool(row["hidden"]),
                bool(row["bidirectional"]),
                bool(row["has_lock"]),
                bool(row["is_locked"]), row["unlock_difficulty"],
                bool(row["is_broken"]),
                bool(row["is_open"]),
                bool(row["has_trap"]),
                (
                    TrapState(row["trap_state"])
                    if row["trap_state"] is not None
                    else None
                ),
                row["trap_detection_difficulty"],
                row["trap_disarm_difficulty"],
                (
                    TrapDamageType(row["trap_damage_type"])
                    if row["trap_damage_type"] is not None
                    else None
                ),
                row["trap_damage"],
            )
            for row in rows
        )

    def get_player_view_state(self, character_id: int) -> PlayerViewState:
        with self._connect() as connection:
            character = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            row = connection.execute(
                """
                SELECT character_id, selected_floor_id, focused_room_id,
                       discord_channel_id, discord_message_id
                FROM player_view_states WHERE character_id = ?
                """,
                (character_id,),
            ).fetchone()
            if row is None:
                room = connection.execute(
                    "SELECT floor_id FROM rooms WHERE id = ?",
                    (character["current_room_id"],),
                ).fetchone()
                selected_floor_id = room["floor_id"] if room else None
                connection.execute(
                    """
                    INSERT INTO player_view_states (
                        character_id, selected_floor_id, focused_room_id
                    ) VALUES (?, ?, ?)
                    """,
                    (character_id, selected_floor_id, character["current_room_id"]),
                )
                return PlayerViewState(
                    character_id, selected_floor_id, character["current_room_id"]
                )
            return PlayerViewState(
                row["character_id"], row["selected_floor_id"], row["focused_room_id"],
                row["discord_channel_id"], row["discord_message_id"],
            )

    def update_player_view_state(
        self,
        character_id: int,
        *,
        selected_floor_id: str | None = None,
        focused_room_id: str | None = None,
        discord_channel_id: int | None = None,
        discord_message_id: int | None = None,
    ) -> PlayerViewState:
        current = self.get_player_view_state(character_id)
        values = PlayerViewState(
            character_id,
            selected_floor_id if selected_floor_id is not None else current.selected_floor_id,
            focused_room_id if focused_room_id is not None else current.focused_room_id,
            discord_channel_id if discord_channel_id is not None else current.discord_channel_id,
            discord_message_id if discord_message_id is not None else current.discord_message_id,
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states SET selected_floor_id = ?, focused_room_id = ?,
                    discord_channel_id = ?, discord_message_id = ?
                WHERE character_id = ?
                """,
                (
                    values.selected_floor_id, values.focused_room_id,
                    values.discord_channel_id, values.discord_message_id, character_id,
                ),
            )
        return values

    def bind_player_view_channel(
        self, character_id: int, channel_id: int
    ) -> PlayerViewState:
        self.get_player_view_state(character_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states
                SET discord_channel_id = ?, discord_message_id = NULL
                WHERE character_id = ?
                """,
                (channel_id, character_id),
            )
        return self.get_player_view_state(character_id)

    def clear_player_view_channel(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE player_view_states
                SET discord_channel_id = NULL, discord_message_id = NULL
                WHERE character_id = ?
                """,
                (character_id,),
            )

    def list_player_view_states(self) -> tuple[PlayerViewState, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id, selected_floor_id, focused_room_id,
                       discord_channel_id, discord_message_id
                FROM player_view_states ORDER BY character_id
                """
            ).fetchall()
        return tuple(
            PlayerViewState(
                row["character_id"], row["selected_floor_id"],
                row["focused_room_id"], row["discord_channel_id"],
                row["discord_message_id"],
            )
            for row in rows
        )

    def request_player_map_refresh(self, character_id: int) -> None:
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone() is None:
                raise CharacterNotFoundError("That character does not exist.")
            self._queue_player_map_refresh(connection, character_id)

    def pending_player_map_refreshes(self) -> tuple[int, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT character_id FROM player_map_refresh_requests
                ORDER BY requested_at, character_id
                """
            ).fetchall()
        return tuple(row["character_id"] for row in rows)

    def clear_player_map_refresh(self, character_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM player_map_refresh_requests WHERE character_id = ?",
                (character_id,),
            )

    @staticmethod
    def _queue_player_map_refresh(
        connection: sqlite3.Connection, character_id: int
    ) -> None:
        connection.execute(
            """
            INSERT INTO player_map_refresh_requests (character_id, requested_at)
            VALUES (?, ?)
            ON CONFLICT(character_id) DO UPDATE SET requested_at = excluded.requested_at
            """,
            (character_id, datetime.now(timezone.utc).isoformat()),
        )

    @classmethod
    def _queue_map_refresh_for_room(
        cls,
        connection: sqlite3.Connection,
        room_id: str,
        *,
        include_focused: bool = False,
    ) -> None:
        rows = connection.execute(
            """
            SELECT characters.id
            FROM characters
            JOIN player_view_states
              ON player_view_states.character_id = characters.id
            WHERE (
                    characters.current_room_id = ?
                    OR (? = 1 AND player_view_states.focused_room_id = ?)
                  )
              AND characters.is_archived = 0
              AND player_view_states.discord_channel_id IS NOT NULL
            """,
            (room_id, int(include_focused), room_id),
        ).fetchall()
        for row in rows:
            cls._queue_player_map_refresh(connection, row["id"])

    def get_game_lock(self) -> GameLock:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT lock_state FROM game_state WHERE id = 1"
            ).fetchone()
        return GameLock(row["lock_state"])

    def set_game_lock(self, state: GameLock) -> GameLock:
        with self._connect() as connection:
            connection.execute(
                "UPDATE game_state SET lock_state = ? WHERE id = 1", (state.value,)
            )
        return state

    def list_enemy_templates(self):
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, description, race, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id
                FROM enemy_templates
                ORDER BY name COLLATE NOCASE, id
                """
            ).fetchall()
        return tuple(self._enemy_template_from_row(row) for row in rows)

    def get_enemy_template(self, template_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, description, race, difficulty_level,
                       strength, dexterity, arcana, vitality, insight, personality,
                       max_hp, armor, magical_resistance, attack_dc, defense_dc,
                       damage, attack_profile, special_ability, typical_behaviour,
                       main_hand_item_id, off_hand_item_id, armor_item_id
                FROM enemy_templates
                WHERE id = ?
                """,
                (template_id,),
            ).fetchone()
        return self._enemy_template_from_row(row) if row is not None else None

    def create_enemy_template(self, template):
        clean_id = self._clean_identifier(
            template.template_id, "Enemy template ID"
        )
        clean_name = self._clean_name(
            template.name, "Enemy template name"
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO enemy_templates (
                        id, name, description, race, difficulty_level,
                        strength, dexterity, arcana, vitality, insight, personality,
                        max_hp, armor, magical_resistance, attack_dc, defense_dc,
                        damage, attack_profile, special_ability, typical_behaviour,
                        main_hand_item_id, off_hand_item_id, armor_item_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        clean_id,
                        clean_name,
                        template.description,
                        template.race,
                        template.difficulty_level,
                        template.strength,
                        template.dexterity,
                        template.arcana,
                        template.vitality,
                        template.insight,
                        template.personality,
                        template.max_hp,
                        template.armor,
                        template.magical_resistance,
                        template.attack_dc,
                        template.defense_dc,
                        template.damage,
                        template.attack_profile,
                        template.special_ability,
                        template.typical_behaviour,
                        template.main_hand_item_id,
                        template.off_hand_item_id,
                        template.armor_item_id,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Enemy template '{clean_id}' already exists."
                ) from error

        created = self.get_enemy_template(clean_id)
        assert created is not None
        return created

    def update_enemy_template(self, template_id: str, template):
        clean_id = self._clean_identifier(
            template_id, "Enemy template ID"
        )
        clean_name = self._clean_name(
            template.name, "Enemy template name"
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE enemy_templates
                SET name = ?, description = ?, race = ?, difficulty_level = ?,
                    strength = ?, dexterity = ?, arcana = ?, vitality = ?,
                    insight = ?, personality = ?, max_hp = ?, armor = ?,
                    magical_resistance = ?, attack_dc = ?, defense_dc = ?,
                    damage = ?, attack_profile = ?, special_ability = ?,
                    typical_behaviour = ?, main_hand_item_id = ?,
                    off_hand_item_id = ?, armor_item_id = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    template.description,
                    template.race,
                    template.difficulty_level,
                    template.strength,
                    template.dexterity,
                    template.arcana,
                    template.vitality,
                    template.insight,
                    template.personality,
                    template.max_hp,
                    template.armor,
                    template.magical_resistance,
                    template.attack_dc,
                    template.defense_dc,
                    template.damage,
                    template.attack_profile,
                    template.special_ability,
                    template.typical_behaviour,
                    template.main_hand_item_id,
                    template.off_hand_item_id,
                    template.armor_item_id,
                    clean_id,
                ),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Enemy template '{clean_id}' does not exist."
                )

            connection.execute(
                """
                UPDATE world_enemies
                SET current_hp = MIN(current_hp, ?)
                WHERE template_id = ?
                """,
                (template.max_hp, clean_id),
            )

        updated = self.get_enemy_template(clean_id)
        assert updated is not None
        return updated

    def remove_enemy_template(self, template_id: str) -> None:
        clean_id = self._clean_identifier(
            template_id, "Enemy template ID"
        )
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    "DELETE FROM enemy_templates WHERE id = ?",
                    (clean_id,),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    "Enemy templates cannot be removed while placed "
                    "enemies use them."
                ) from error

            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Enemy template '{clean_id}' does not exist."
                )

    def create_enemy_instance(
        self,
        room_id: str,
        template_id: str,
        *,
        instance_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ):
        template = self.get_enemy_template(template_id)
        if template is None:
            raise NotFoundError(
                f"Enemy template '{template_id}' does not exist."
            )

        clean_id = self._clean_identifier(
            instance_id or f"{template.template_id}_{uuid4().hex[:12]}",
            "Enemy ID",
        )
        clean_name = self._clean_name(
            name or template.name, "Enemy name"
        )
        resolved_description = (
            template.description if description is None else description
        )

        with self._connect() as connection:
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO world_entities (
                        id, room_id, kind, name, description
                    ) VALUES (?, ?, 'enemy', ?, ?)
                    """,
                    (
                        clean_id,
                        room_id,
                        clean_name,
                        resolved_description,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO world_enemies (
                        entity_id, template_id, current_hp, status
                    ) VALUES (?, ?, ?, 'active')
                    """,
                    (
                        clean_id,
                        template.template_id,
                        template.max_hp,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(
                    f"Enemy '{clean_id}' already exists."
                ) from error

        created = self.get_enemy_instance(clean_id)
        assert created is not None
        return created

    def get_enemy_instance(self, enemy_id: str):
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT entity.id, entity.room_id, enemy.template_id,
                       entity.name, entity.description,
                       enemy.current_hp, enemy.status
                FROM world_entities AS entity
                JOIN world_enemies AS enemy
                  ON enemy.entity_id = entity.id
                WHERE entity.id = ? AND entity.kind = 'enemy'
                """,
                (enemy_id,),
            ).fetchone()

        return (
            self._enemy_instance_from_row(row)
            if row is not None
            else None
        )

    def list_room_enemy_instances(self, room_id: str):
        with self._connect() as connection:
            self._require_room(connection, room_id)
            rows = connection.execute(
                """
                SELECT entity.id, entity.room_id, enemy.template_id,
                       entity.name, entity.description,
                       enemy.current_hp, enemy.status
                FROM world_entities AS entity
                JOIN world_enemies AS enemy
                  ON enemy.entity_id = entity.id
                WHERE entity.room_id = ? AND entity.kind = 'enemy'
                ORDER BY entity.name COLLATE NOCASE, entity.id
                """,
                (room_id,),
            ).fetchall()

        return tuple(
            self._enemy_instance_from_row(row)
            for row in rows
        )

    def update_enemy_instance(self, enemy):
        template = self.get_enemy_template(enemy.template_id)
        if template is None:
            raise NotFoundError(
                f"Enemy template '{enemy.template_id}' does not exist."
            )

        if enemy.current_hp < 0 or enemy.current_hp > template.max_hp:
            raise ValueError(
                f"Enemy HP must be between 0 and {template.max_hp}."
            )

        clean_name = self._clean_name(enemy.name, "Enemy name")

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM world_entities
                WHERE id = ? AND kind = 'enemy'
                """,
                (enemy.id,),
            ).fetchone()

            if existing is None:
                raise NotFoundError(
                    f"Enemy '{enemy.id}' does not exist."
                )

            connection.execute(
                """
                UPDATE world_entities
                SET name = ?, description = ?
                WHERE id = ?
                """,
                (
                    clean_name,
                    enemy.description,
                    enemy.id,
                ),
            )
            connection.execute(
                """
                UPDATE world_enemies
                SET current_hp = ?, status = ?
                WHERE entity_id = ?
                """,
                (
                    enemy.current_hp,
                    enemy.status.value,
                    enemy.id,
                ),
            )

        updated = self.get_enemy_instance(enemy.id)
        assert updated is not None
        return updated

    @staticmethod
    def _enemy_template_from_row(row):
        from .enemies import EnemyTemplate

        return EnemyTemplate(
            template_id=row["id"],
            name=row["name"],
            description=row["description"],
            race=row["race"],
            difficulty_level=row["difficulty_level"],
            strength=row["strength"],
            dexterity=row["dexterity"],
            arcana=row["arcana"],
            vitality=row["vitality"],
            insight=row["insight"],
            personality=row["personality"],
            max_hp=row["max_hp"],
            armor=row["armor"],
            magical_resistance=row["magical_resistance"],
            attack_dc=row["attack_dc"],
            defense_dc=row["defense_dc"],
            damage=row["damage"],
            attack_profile=row["attack_profile"],
            special_ability=row["special_ability"],
            typical_behaviour=row["typical_behaviour"],
            main_hand_item_id=row["main_hand_item_id"],
            off_hand_item_id=row["off_hand_item_id"],
            armor_item_id=row["armor_item_id"],
        )

    @staticmethod
    def _enemy_instance_from_row(row):
        from .enemies import EnemyInstance, EnemyStatus

        return EnemyInstance(
            id=row["id"],
            room_id=row["room_id"],
            template_id=row["template_id"],
            name=row["name"],
            current_hp=row["current_hp"],
            status=EnemyStatus(row["status"]),
            description=row["description"],
        )

    def create_world_entity(
        self,
        entity_id: str,
        room_id: str,
        kind: EntityKind,
        name: str,
        description: str | None = None,
    ) -> WorldEntity:
        entity_id = self._clean_identifier(entity_id, "Entity ID")
        name = self._clean_name(name, "Entity name")
        with self._connect() as connection:
            self._require_room(connection, room_id)
            try:
                connection.execute(
                    """
                    INSERT INTO world_entities (id, room_id, kind, name, description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (entity_id, room_id, kind.value, name, description),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError(f"Entity '{entity_id}' already exists.") from error
        return WorldEntity(entity_id, room_id, kind, name, description)

    def move_world_entity(self, entity_id: str, room_id: str) -> WorldEntity:
        with self._connect() as connection:
            self._require_room(connection, room_id)
            cursor = connection.execute(
                "UPDATE world_entities SET room_id = ? WHERE id = ?",
                (room_id, entity_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(f"Entity '{entity_id}' does not exist.")
            row = connection.execute(
                "SELECT id, room_id, kind, name, description FROM world_entities WHERE id = ?",
                (entity_id,),
            ).fetchone()
        return self._to_entity(row)

    def remove_world_entity(self, entity_id: str) -> None:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM world_entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if exists is None:
                raise NotFoundError(f"Entity '{entity_id}' does not exist.")
            connection.execute(
                "DELETE FROM inventory_stacks WHERE holder_kind = 'entity' AND holder_id = ?",
                (entity_id,),
            )
            connection.execute("DELETE FROM world_entities WHERE id = ?", (entity_id,))

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

    def add_item(
        self, holder: InventoryHolder, item_id: str, quantity: int = 1
    ) -> ItemStack:
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            item = self._require_item(connection, item_id)
            existing = self._stack_quantity(connection, holder, item.id)
            if not item.stackable and (quantity != 1 or existing):
                raise InvalidTransferError(f"{item.name} is not stackable.")
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (holder.kind.value, holder.id, item.id, quantity),
            )
            if holder.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, holder.id)
        return ItemStack(item, existing + quantity)

    def remove_item(self, holder: InventoryHolder, item_id: str) -> None:
        """Remove an entire item stack from a world inventory."""
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            cursor = connection.execute(
                """
                DELETE FROM inventory_stacks
                WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                """,
                (holder.kind.value, holder.id, item_id),
            )
            if cursor.rowcount == 0:
                raise NotFoundError(
                    f"Item '{item_id}' does not exist in that inventory."
                )
            if holder.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, holder.id)

    def get_inventory(self, holder: InventoryHolder) -> tuple[ItemStack, ...]:
        with self._connect() as connection:
            self._validate_holder(connection, holder)
            rows = connection.execute(
                """
                SELECT i.id, i.name, i.description, i.stackable, s.quantity
                FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
                WHERE s.holder_kind = ? AND s.holder_id = ?
                ORDER BY i.name COLLATE NOCASE, i.id
                """,
                (holder.kind.value, holder.id),
            ).fetchall()
            return tuple(
                ItemStack(
                    Item(row["id"], row["name"], row["description"], bool(row["stackable"])),
                    row["quantity"],
                )
                for row in rows
            )

    def take_world_item_into_character_inventory(
        self,
        source: InventoryHolder,
        character_id: int,
        item_query: str,
        template_id: str,
        *,
        quantity: int,
        durability: int | None,
        stackable: bool,
    ) -> ItemStack:
        """Atomically move a room/entity stack into the rich character inventory."""
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, source)
            self._validate_holder(connection, InventoryHolder.character(character_id))
            item = self._resolve_held_item(connection, source, item_query)
            source_quantity = self._stack_quantity(connection, source, item.id)
            if source_quantity < quantity:
                raise InvalidTransferError(
                    f"Only {source_quantity} × {item.name} is available."
                )
            if not stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            existing_rows = []
            if stackable:
                existing_rows = connection.execute(
                    """
                    SELECT instance_id, quantity FROM character_items
                    WHERE character_id = ? AND template_id = ?
                      AND parent_container_id IS NULL
                    ORDER BY rowid
                    """,
                    (character_id, template_id),
                ).fetchall()

            remaining = source_quantity - quantity
            if remaining:
                connection.execute(
                    """
                    UPDATE inventory_stacks SET quantity = ?
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (remaining, source.kind.value, source.id, item.id),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM inventory_stacks
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (source.kind.value, source.id, item.id),
                )

            if existing_rows:
                primary = existing_rows[0]
                combined_quantity = quantity + sum(
                    row["quantity"] for row in existing_rows
                )
                connection.execute(
                    """
                    UPDATE character_items SET quantity = ?
                    WHERE instance_id = ?
                    """,
                    (combined_quantity, primary["instance_id"]),
                )
                duplicate_ids = [
                    row["instance_id"] for row in existing_rows[1:]
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
            else:
                connection.execute(
                    """
                    INSERT INTO character_items (
                        instance_id, character_id, template_id, quantity, durability
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, character_id, template_id, quantity, durability),
                )
            if source.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, source.id)
        return ItemStack(item, quantity)

    def drop_character_inventory_item(
        self,
        character_id: int,
        instance_id: str,
        destination: InventoryHolder,
        item: Item,
        *,
        quantity: int,
    ) -> ItemStack:
        """Atomically move a rich inventory item into a room/entity stack."""
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, destination)
            row = connection.execute(
                """
                SELECT template_id, quantity, parent_container_id
                FROM character_items
                WHERE character_id = ? AND instance_id = ?
                """,
                (character_id, instance_id),
            ).fetchone()
            if row is None:
                raise InvalidTransferError("That item is not in this inventory.")
            if row["parent_container_id"] is not None:
                raise InvalidTransferError("Move the item out of its container first.")
            if connection.execute(
                "SELECT 1 FROM character_equipment WHERE character_id = ? AND item_instance_id = ?",
                (character_id, instance_id),
            ).fetchone():
                raise InvalidTransferError("Unequip that item before dropping it.")
            if connection.execute(
                "SELECT 1 FROM character_items WHERE parent_container_id = ? LIMIT 1",
                (instance_id,),
            ).fetchone():
                raise InvalidTransferError("Empty that container before dropping it.")
            if row["quantity"] < quantity:
                raise InvalidTransferError(
                    f"Only {row['quantity']} × {item.name} is available."
                )
            if not item.stackable and quantity != 1:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            connection.execute(
                """
                INSERT INTO items (id, name, description, stackable)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    stackable = excluded.stackable
                """,
                (item.id, item.name, item.description, int(item.stackable)),
            )
            destination_quantity = self._stack_quantity(connection, destination, item.id)
            if not item.stackable and destination_quantity:
                raise InvalidTransferError(f"{item.name} is not stackable.")

            remaining = row["quantity"] - quantity
            if remaining:
                connection.execute(
                    "UPDATE character_items SET quantity = ? WHERE instance_id = ?",
                    (remaining, instance_id),
                )
            else:
                connection.execute(
                    "DELETE FROM character_items WHERE instance_id = ?",
                    (instance_id,),
                )
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (destination.kind.value, destination.id, item.id, quantity),
            )
            if destination.kind is HolderKind.ROOM:
                self._queue_map_refresh_for_room(connection, destination.id)
        return ItemStack(item, quantity)

    def transfer_item(
        self,
        source: InventoryHolder,
        destination: InventoryHolder,
        item_query: str,
        quantity: int = 1,
    ) -> ItemStack:
        if source == destination:
            raise InvalidTransferError("Source and destination must be different.")
        if quantity <= 0:
            raise InvalidTransferError("Quantity must be greater than zero.")
        with self._connect() as connection:
            self._validate_holder(connection, source)
            self._validate_holder(connection, destination)
            item = self._resolve_held_item(connection, source, item_query)
            source_quantity = self._stack_quantity(connection, source, item.id)
            if source_quantity < quantity:
                raise InvalidTransferError(
                    f"Only {source_quantity} × {item.name} is available."
                )
            destination_quantity = self._stack_quantity(connection, destination, item.id)
            if not item.stackable and (quantity != 1 or destination_quantity):
                raise InvalidTransferError(f"{item.name} is not stackable.")

            remaining = source_quantity - quantity
            if remaining:
                connection.execute(
                    """
                    UPDATE inventory_stacks SET quantity = ?
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (remaining, source.kind.value, source.id, item.id),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM inventory_stacks
                    WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
                    """,
                    (source.kind.value, source.id, item.id),
                )
            connection.execute(
                """
                INSERT INTO inventory_stacks (holder_kind, holder_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(holder_kind, holder_id, item_id) DO UPDATE
                SET quantity = quantity + excluded.quantity
                """,
                (destination.kind.value, destination.id, item.id, quantity),
            )
            for holder in (source, destination):
                if holder.kind is HolderKind.ROOM:
                    self._queue_map_refresh_for_room(connection, holder.id)
        return ItemStack(item, quantity)

    def get_dice_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dice_color"] if row else DEFAULT_DICE_COLOR

    def get_dm_portrait(self, discord_user_id: int) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dm_portrait_key
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dm_portrait_key"] if row else None

    def set_dm_portrait(
        self, discord_user_id: int, portrait_key: str | None
    ) -> str | None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (
                    discord_user_id, dice_color, dm_portrait_key
                )
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dm_portrait_key = excluded.dm_portrait_key
                """,
                (discord_user_id, DEFAULT_DICE_COLOR, portrait_key),
            )
        return portrait_key

    def set_dice_color(self, discord_user_id: int, color: str) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (discord_user_id, dice_color)
                VALUES (?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_color = excluded.dice_color
                """,
                (discord_user_id, normalized_color),
            )
        return normalized_color

    def get_dice_edge_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_edge_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dice_edge_color"] if row else DEFAULT_DICE_EDGE_COLOR

    def set_dice_edge_color(self, discord_user_id: int, color: str) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (discord_user_id, dice_color, dice_edge_color)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_edge_color = excluded.dice_edge_color
                """,
                (discord_user_id, DEFAULT_DICE_COLOR, normalized_color),
            )
        return normalized_color

    def get_dice_number_color(self, discord_user_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT dice_number_color
                FROM user_preferences
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return row["dice_number_color"] if row else DEFAULT_DICE_NUMBER_COLOR

    def set_dice_number_color(self, discord_user_id: int, color: str) -> str:
        normalized_color = normalize_dice_color(color)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_preferences (discord_user_id, dice_color, dice_number_color)
                VALUES (?, ?, ?)
                ON CONFLICT(discord_user_id) DO UPDATE
                SET dice_number_color = excluded.dice_number_color
                """,
                (discord_user_id, DEFAULT_DICE_COLOR, normalized_color),
            )
        return normalized_color

    @staticmethod
    def _ensure_character_combat_state_row(
        connection: sqlite3.Connection,
        character_id: int,
    ) -> sqlite3.Row:
        character = connection.execute(
            """
            SELECT id, hp, max_hp FROM characters
            WHERE id = ? AND is_archived = 0
            """,
            (character_id,),
        ).fetchone()
        if character is None:
            raise CharacterNotFoundError(
                f"Character {character_id} does not exist."
            )
        connection.execute(
            """
            INSERT OR IGNORE INTO character_combat_states (
                character_id, status, failed_death_saves
            ) VALUES (
                ?,
                CASE
                    WHEN ? <= -? THEN 'dead'
                    WHEN ? <= 0 THEN 'downed'
                    ELSE 'active'
                END,
                0
            )
            """,
            (
                character_id,
                character["hp"],
                character["max_hp"],
                character["hp"],
            ),
        )
        row = connection.execute(
            """
            SELECT character_id, status, failed_death_saves
            FROM character_combat_states
            WHERE character_id = ?
            """,
            (character_id,),
        ).fetchone()
        assert row is not None
        return row

    @staticmethod
    def _combat_state_from_row(row: sqlite3.Row) -> CharacterCombatState:
        return CharacterCombatState(
            character_id=int(row["character_id"]),
            status=CharacterCombatStatus(row["status"]),
            failed_death_saves=int(row["failed_death_saves"]),
        )

    def get_character_combat_state(
        self,
        character_id: int,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            row = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            return self._combat_state_from_row(row)

    @classmethod
    def _apply_character_damage(
        cls,
        connection: sqlite3.Connection,
        character_id: int,
        amount: int,
    ) -> tuple[int, int, CharacterCombatStatus]:
        character = connection.execute(
            """
            SELECT hp, max_hp FROM characters
            WHERE id = ? AND is_archived = 0
            """,
            (character_id,),
        ).fetchone()
        if character is None:
            raise CharacterNotFoundError(
                f"Character {character_id} does not exist."
            )
        state = cls._ensure_character_combat_state_row(
            connection,
            character_id,
        )
        old_hp = int(character["hp"])
        max_hp = int(character["max_hp"])
        new_hp = max(-max_hp, old_hp - amount)

        if new_hp <= -max_hp:
            new_status = CharacterCombatStatus.DEAD
        elif new_hp <= 0:
            new_status = CharacterCombatStatus.DOWNED
        elif state["status"] == CharacterCombatStatus.RECOVERING.value:
            new_status = CharacterCombatStatus.RECOVERING
        else:
            new_status = CharacterCombatStatus.ACTIVE

        failed_death_saves = int(state["failed_death_saves"])
        if old_hp > 0 and new_hp <= 0:
            failed_death_saves = 0

        connection.execute(
            "UPDATE characters SET hp = ? WHERE id = ?",
            (new_hp, character_id),
        )
        connection.execute(
            """
            UPDATE character_combat_states
            SET status = ?, failed_death_saves = ?
            WHERE character_id = ?
            """,
            (
                new_status.value,
                failed_death_saves,
                character_id,
            ),
        )
        return new_hp, max_hp, new_status

    def damage(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Damage must be greater than 0.")
        character = self._require_character(discord_user_id)
        assert character.character_id is not None
        return self.damage_character_by_id(character.character_id, amount)

    def damage_character_by_id(
        self,
        character_id: int,
        amount: int,
    ) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Damage must be greater than 0.")
        with self._connect() as connection:
            self._apply_character_damage(
                connection,
                character_id,
                amount,
            )
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            assert row is not None
            return self._to_character_with_skills(connection, row)

    def heal(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Healing must be greater than 0.")
        character = self._require_character(discord_user_id)
        assert character.character_id is not None
        return self.heal_character_by_id(character.character_id, amount)

    def heal_character_by_id(
        self,
        character_id: int,
        amount: int,
    ) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Healing must be greater than 0.")
        with self._connect() as connection:
            character = connection.execute(
                """
                SELECT hp, max_hp FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError(
                    f"Character {character_id} does not exist."
                )
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            if state["status"] == CharacterCombatStatus.DEAD.value:
                raise InvalidHitPointsError(
                    "Dead characters cannot be restored by normal healing."
                )

            old_hp = int(character["hp"])
            max_hp = int(character["max_hp"])
            new_hp = min(max_hp, old_hp + amount)
            if old_hp <= 0 < new_hp:
                new_status = CharacterCombatStatus.RECOVERING
                failed_death_saves = 0
            else:
                new_status = CharacterCombatStatus(state["status"])
                failed_death_saves = int(state["failed_death_saves"])

            connection.execute(
                "UPDATE characters SET hp = ? WHERE id = ?",
                (new_hp, character_id),
            )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (
                    new_status.value,
                    failed_death_saves,
                    character_id,
                ),
            )
            row = connection.execute(
                """
                SELECT id, discord_user_id, name, hp, max_hp, stance,
                       lineage, race, age, gender,
                       strength, dexterity, arcana, vitality, insight, personality,
                       is_active, is_archived, portrait_key, current_room_id
                FROM characters
                WHERE id = ? AND is_archived = 0
                """,
                (character_id,),
            ).fetchone()
            assert row is not None
            return self._to_character_with_skills(connection, row)

    def record_death_save(
        self,
        character_id: int,
        *,
        success: bool,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            if state["status"] != CharacterCombatStatus.DOWNED.value:
                raise InvalidHitPointsError(
                    "Only a downed character can make a death save."
                )
            if success:
                status = CharacterCombatStatus.STABLE
                failures = 0
            else:
                failures = min(3, int(state["failed_death_saves"]) + 1)
                status = (
                    CharacterCombatStatus.DEAD
                    if failures >= 3
                    else CharacterCombatStatus.DOWNED
                )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = ?
                WHERE character_id = ?
                """,
                (status.value, failures, character_id),
            )
            return CharacterCombatState(
                character_id,
                status,
                failures,
            )

    def finish_short_rest(
        self,
        character_id: int,
    ) -> CharacterCombatState:
        with self._connect() as connection:
            state = self._ensure_character_combat_state_row(
                connection,
                character_id,
            )
            status = CharacterCombatStatus(state["status"])
            if status is CharacterCombatStatus.RECOVERING:
                status = CharacterCombatStatus.ACTIVE
                connection.execute(
                    """
                    UPDATE character_combat_states
                    SET status = 'active'
                    WHERE character_id = ?
                    """,
                    (character_id,),
                )
            return CharacterCombatState(
                character_id,
                status,
                int(state["failed_death_saves"]),
            )

    def set_hp(self, discord_user_id: int, hp: int) -> Character:
        character = self._require_character(discord_user_id)
        if not -character.max_hp <= hp <= character.max_hp:
            raise InvalidHitPointsError(
                f"HP must be between {-character.max_hp} and "
                f"{character.max_hp} for {character.name}."
            )
        assert character.character_id is not None
        with self._connect() as connection:
            self._ensure_character_combat_state_row(
                connection,
                character.character_id,
            )
            if hp <= -character.max_hp:
                status = CharacterCombatStatus.DEAD
            elif hp <= 0:
                status = CharacterCombatStatus.DOWNED
            else:
                status = CharacterCombatStatus.ACTIVE
            connection.execute(
                """
                UPDATE characters SET hp = ?
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (hp, discord_user_id),
            )
            connection.execute(
                """
                UPDATE character_combat_states
                SET status = ?, failed_death_saves = 0
                WHERE character_id = ?
                """,
                (status.value, character.character_id),
            )
        return self._require_character(discord_user_id)

    def set_stance(self, discord_user_id: int, stance: Stance) -> Character:
        self._require_character(discord_user_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE characters SET stance = ?
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (stance.value, discord_user_id),
            )
        return self._require_character(discord_user_id)

    def _require_character(self, discord_user_id: int) -> Character:
        character = self.get_character(discord_user_id)
        if character is None:
            raise CharacterNotFoundError("That Discord user does not have a character.")
        return character

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
    def _validate_editor_coordinate(value: float, axis: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Editor {axis} coordinate must be a number.")
        coordinate = float(value)
        if not math.isfinite(coordinate) or abs(coordinate) > 1_000_000:
            raise ValueError(f"Editor {axis} coordinate is outside the valid range.")
        return coordinate

    @staticmethod
    def _validate_room_dimension(value: float, label: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Room {label} must be a number.")
        dimension = float(value)
        if not math.isfinite(dimension) or dimension <= 0 or dimension > 1_000_000:
            raise ValueError(f"Room {label} must be a positive finite number.")
        return dimension

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

    @staticmethod
    def _record_room_visit(
        connection: sqlite3.Connection, character_id: int, room_id: str
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """
            INSERT INTO character_room_knowledge (
                character_id, room_id, state, source, first_visited_at, last_visited_at
            ) VALUES (?, ?, 'visited', 'discovered', ?, ?)
            ON CONFLICT(character_id, room_id) DO UPDATE SET
                state = 'visited',
                source = 'discovered',
                first_visited_at = COALESCE(
                    character_room_knowledge.first_visited_at, excluded.first_visited_at
                ),
                last_visited_at = excluded.last_visited_at,
                shared_by_character_id = NULL
            """,
            (character_id, room_id, now, now),
        )
        connection.execute(
            """
            UPDATE player_view_states
            SET selected_floor_id = (SELECT floor_id FROM rooms WHERE id = ?),
                focused_room_id = ?
            WHERE character_id = ?
            """,
            (room_id, room_id, character_id),
        )
        Database._record_visible_connections(connection, character_id, room_id)

    @staticmethod
    def _record_visible_connections(
        connection: sqlite3.Connection, character_id: int, room_id: str
    ) -> None:
        """Reveal every currently visible exit from a character's room."""
        connection_rows = connection.execute(
            """
                SELECT id, from_room_id, to_room_id, bidirectional,
                       connection_type, is_open
            FROM room_connections
            WHERE hidden = 0 AND (
                from_room_id = ? OR (to_room_id = ? AND bidirectional = 1)
            )
            """,
            (room_id, room_id),
        ).fetchall()
        for connection_row in connection_rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO character_known_connections (
                    character_id, connection_id
                ) VALUES (?, ?)
                """,
                (character_id, connection_row["id"]),
            )
            adjacent_room_id = (
                connection_row["to_room_id"]
                if connection_row["from_room_id"] == room_id
                else connection_row["from_room_id"]
            )
            if (
                ConnectionType(connection_row["connection_type"])
                is ConnectionType.DOOR
                and not connection_row["is_open"]
            ):
                continue
            connection.execute(
                """
                INSERT INTO character_room_knowledge (
                    character_id, room_id, state, source
                ) VALUES (?, ?, 'known', 'discovered')
                ON CONFLICT(character_id, room_id) DO NOTHING
                """,
                (character_id, adjacent_room_id),
            )

    @staticmethod
    def _to_knowledge(
        row: sqlite3.Row, connection_ids: tuple[str, ...]
    ) -> CharacterRoomKnowledge:
        def parsed(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return CharacterRoomKnowledge(
            row["character_id"],
            row["room_id"],
            KnowledgeState(row["state"]),
            KnowledgeSource(row["source"]),
            connection_ids,
            parsed(row["first_visited_at"]),
            parsed(row["last_visited_at"]),
            row["last_seen_scene_id"],
            row["shared_by_character_id"],
        )

    @staticmethod
    def _require_item(connection: sqlite3.Connection, item_id: str) -> Item:
        row = connection.execute(
            "SELECT id, name, description, stackable FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Item '{item_id}' does not exist.")
        return Item(row["id"], row["name"], row["description"], bool(row["stackable"]))

    @staticmethod
    def _validate_holder(
        connection: sqlite3.Connection, holder: InventoryHolder
    ) -> None:
        if holder.kind.value == "character":
            try:
                character_id = int(holder.id)
            except ValueError as error:
                raise NotFoundError(f"Character '{holder.id}' does not exist.") from error
            exists = connection.execute(
                "SELECT 1 FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
        elif holder.kind.value == "room":
            exists = connection.execute(
                "SELECT 1 FROM rooms WHERE id = ?", (holder.id,)
            ).fetchone()
        else:
            exists = connection.execute(
                "SELECT 1 FROM world_entities WHERE id = ?", (holder.id,)
            ).fetchone()
        if exists is None:
            raise NotFoundError(
                f"{holder.kind.value.title()} holder '{holder.id}' does not exist."
            )

    @staticmethod
    def _stack_quantity(
        connection: sqlite3.Connection, holder: InventoryHolder, item_id: str
    ) -> int:
        row = connection.execute(
            """
            SELECT quantity FROM inventory_stacks
            WHERE holder_kind = ? AND holder_id = ? AND item_id = ?
            """,
            (holder.kind.value, holder.id, item_id),
        ).fetchone()
        return row["quantity"] if row else 0

    @staticmethod
    def _resolve_held_item(
        connection: sqlite3.Connection,
        holder: InventoryHolder,
        item_query: str,
    ) -> Item:
        query = item_query.strip()
        rows = connection.execute(
            """
            SELECT i.id, i.name, i.description, i.stackable
            FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
            WHERE s.holder_kind = ? AND s.holder_id = ?
              AND (i.id = ? OR i.name = ? COLLATE NOCASE)
            ORDER BY CASE WHEN i.id = ? THEN 0 ELSE 1 END
            """,
            (holder.kind.value, holder.id, query, query, query),
        ).fetchall()
        if not rows:
            raise InvalidTransferError(f"The source does not contain '{item_query}'.")
        exact_ids = [row for row in rows if row["id"] == query]
        if not exact_ids and len(rows) > 1:
            raise InvalidTransferError(
                f"More than one item is named '{item_query}'; use an item ID."
            )
        row = exact_ids[0] if exact_ids else rows[0]
        return Item(row["id"], row["name"], row["description"], bool(row["stackable"]))

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> WorldEntity:
        return WorldEntity(
            row["id"],
            row["room_id"],
            EntityKind(row["kind"]),
            row["name"],
            row["description"],
        )

    @classmethod
    def _to_room(cls, connection: sqlite3.Connection, row: sqlite3.Row) -> Room:
        position = connection.execute(
            "SELECT x, y FROM room_editor_metadata WHERE room_id = ?", (row["id"],)
        ).fetchone()
        exits = tuple(
            Exit(exit_row["name"], exit_row["destination_room_id"])
            for exit_row in connection.execute(
                """
                SELECT name, destination_room_id FROM room_exits
                WHERE room_id = ? ORDER BY name COLLATE NOCASE
                """,
                (row["id"],),
            )
        )
        entities = tuple(
            cls._to_entity(entity_row)
            for entity_row in connection.execute(
                """
                SELECT id, room_id, kind, name, description FROM world_entities
                WHERE room_id = ? ORDER BY name COLLATE NOCASE, id
                """,
                (row["id"],),
            )
        )
        character_rows = connection.execute(
            """
            SELECT id, discord_user_id, name, hp, max_hp, stance,
                   lineage, race, age, gender,
                   strength, dexterity, arcana, vitality, insight, personality,
                   is_active, is_archived, portrait_key, current_room_id
            FROM characters
            WHERE current_room_id = ? AND is_archived = 0
            ORDER BY name COLLATE NOCASE, id
            """,
            (row["id"],),
        ).fetchall()
        characters = tuple(
            cls._to_character_with_skills(connection, character_row)
            for character_row in character_rows
        )
        loose_items = tuple(
            ItemStack(
                Item(
                    item_row["id"],
                    item_row["name"],
                    item_row["description"],
                    bool(item_row["stackable"]),
                ),
                item_row["quantity"],
            )
            for item_row in connection.execute(
                """
                SELECT i.id, i.name, i.description, i.stackable, s.quantity
                FROM inventory_stacks AS s JOIN items AS i ON i.id = s.item_id
                WHERE s.holder_kind = 'room' AND s.holder_id = ?
                ORDER BY i.name COLLATE NOCASE, i.id
                """,
                (row["id"],),
            )
        )
        return Room(
            row["id"], row["area_id"], row["name"], row["description"],
            exits, entities, characters, loose_items,
            row["floor_id"],
            position["x"] if position else 0.0,
            position["y"] if position else 0.0,
            row["width"],
            row["height"],
            row["scene_image_path"],
            row["scene_image_url"],
            row["scene_prompt"],
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

    @staticmethod
    def _to_character_with_skills(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> Character:
        skill_rows = connection.execute(
            """
            SELECT skill, rank FROM character_skills
            WHERE character_id = ? ORDER BY skill
            """,
            (row["id"],),
        ).fetchall()
        return Database._to_character(row, skill_rows)

    @staticmethod
    def _to_character(
        row: sqlite3.Row, skill_rows: list[sqlite3.Row] | None = None
    ) -> Character:
        attribute_columns = {
            "Strength": "strength",
            "Dexterity": "dexterity",
            "Arcana": "arcana",
            "Vitality": "vitality",
            "Insight": "insight",
            "Personality": "personality",
        }
        return Character(
            discord_user_id=row["discord_user_id"],
            name=row["name"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            stance=Stance(row["stance"]),
            lineage=row["lineage"],
            race=row["race"],
            age=row["age"],
            gender=row["gender"],
            attributes={
                attribute: row[column]
                for attribute, column in attribute_columns.items()
                if row[column] is not None
            },
            skills={
                skill_row["skill"]: skill_row["rank"]
                for skill_row in (skill_rows or [])
            },
            character_id=row["id"],
            is_active=bool(row["is_active"]),
            is_archived=bool(row["is_archived"]),
            portrait_key=row["portrait_key"],
            current_room_id=row["current_room_id"],
        )
