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
from .models import Character, CharacterSheetViewState, Stance
from .dungeon import (
    CharacterLocation,
    CharacterRoomKnowledge,
    ConnectionType,
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
    InvalidMovementError,
    InvalidTransferError,
    InventoryHolder,
    Item,
    ItemStack,
    NotFoundError,
    Room,
    RoomEditorNode,
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

    def initialize(self) -> None:
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            self._initialize_characters(connection)
            self._initialize_world(connection)
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
    def _create_character_tables(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                hp INTEGER NOT NULL CHECK (hp >= 0 AND hp <= max_hp),
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
                cls._create_character_tables(connection)

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
            CREATE TABLE IF NOT EXISTS game_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                lock_state TEXT NOT NULL CHECK (
                    lock_state IN ('none', 'movement_locked', 'all_actions_locked')
                )
            );
            INSERT OR IGNORE INTO game_state (id, lock_state) VALUES (1, 'none');
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
                row = connection.execute(
                    """
                    SELECT instance_id FROM character_items
                    WHERE character_id = ? AND template_id = ?
                      AND parent_container_id IS ?
                    ORDER BY rowid LIMIT 1
                    """,
                    (character_id, template_id, parent_container_id),
                ).fetchone()
                if row is not None:
                    connection.execute(
                        """
                        UPDATE character_items SET quantity = quantity + ?
                        WHERE instance_id = ?
                        """,
                        (quantity, row["instance_id"]),
                    )
                    return row["instance_id"]
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
    ) -> RoomConnection:
        exit_name = self._clean_name(exit_name, "Exit name")
        if return_exit_name is not None:
            return_exit_name = self._clean_name(return_exit_name, "Return exit name")
        with self._connect() as connection:
            source_room = self._require_room(connection, room_id)
            destination_room = self._require_room(connection, destination_room_id)
            if source_room["area_id"] != destination_room["area_id"]:
                raise InvalidMovementError("Rooms in different areas cannot be connected.")
            duplicate = connection.execute(
                """
                SELECT 1 FROM room_exits
                WHERE room_id = ? AND (name = ? COLLATE NOCASE OR destination_room_id = ?)
                """,
                (room_id, exit_name, destination_room_id),
            ).fetchone()
            if duplicate:
                raise InvalidMovementError("That room connection already exists.")
            if return_exit_name is not None:
                reverse_duplicate = connection.execute(
                    """
                    SELECT 1 FROM room_exits
                    WHERE room_id = ? AND (
                        name = ? COLLATE NOCASE OR destination_room_id = ?
                    )
                    """,
                    (destination_room_id, return_exit_name, room_id),
                ).fetchone()
                if reverse_duplicate:
                    raise InvalidMovementError("That return connection already exists.")
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
                    connection_type, hidden, bidirectional
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
        return RoomConnection(
            connection_id,
            room_id,
            destination_room_id,
            connection_type,
            hidden,
            return_exit_name is not None,
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
                       links.bidirectional, links.hidden
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
            cursor = connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ? AND is_archived = 0",
                (room_id, character_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That character does not exist.")
            self._record_room_visit(connection, character_id, room_id)
        room = self.get_room(room_id)
        assert room is not None
        return room

    def ensure_character_location_knowledge(self, character_id: int) -> None:
        """Repair legacy locations that predate player-specific map knowledge."""
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

    def move_character(self, character_id: int, destination: str) -> Room:
        destination = destination.strip()
        with self._connect() as connection:
            character = connection.execute(
                "SELECT current_room_id FROM characters WHERE id = ? AND is_archived = 0",
                (character_id,),
            ).fetchone()
            if character is None:
                raise CharacterNotFoundError("That character does not exist.")
            current_room_id = character["current_room_id"]
            if current_room_id is None:
                raise InvalidMovementError("The character is not currently in a room.")
            exit_row = connection.execute(
                """
                SELECT destination_room_id FROM room_exits
                WHERE room_id = ? AND (name = ? COLLATE NOCASE OR destination_room_id = ?)
                """,
                (current_room_id, destination, destination),
            ).fetchone()
            if exit_row is None:
                raise InvalidMovementError(
                    f"'{destination}' is not an exit from the current room."
                )
            destination_id = exit_row["destination_room_id"]
            self._require_room(connection, destination_id)
            connection.execute(
                "UPDATE characters SET current_room_id = ? WHERE id = ?",
                (destination_id, character_id),
            )
            self._record_room_visit(connection, character_id, destination_id)
        room = self.get_room(destination_id)
        assert room is not None
        return room

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
                       c.hidden, c.bidirectional
                FROM room_connections AS c
                JOIN character_known_connections AS known
                  ON known.connection_id = c.id
                JOIN character_room_knowledge AS source_room
                  ON source_room.character_id = known.character_id
                 AND source_room.room_id = c.from_room_id
                JOIN character_room_knowledge AS target_room
                  ON target_room.character_id = known.character_id
                 AND target_room.room_id = c.to_room_id
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
        return ItemStack(item, existing + quantity)

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

            existing = None
            if stackable:
                existing = connection.execute(
                    """
                    SELECT instance_id FROM character_items
                    WHERE character_id = ? AND template_id = ?
                      AND parent_container_id IS NULL
                    ORDER BY rowid LIMIT 1
                    """,
                    (character_id, template_id),
                ).fetchone()

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

            if existing is not None:
                connection.execute(
                    """
                    UPDATE character_items SET quantity = quantity + ?
                    WHERE instance_id = ?
                    """,
                    (quantity, existing["instance_id"]),
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

    def damage(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Damage must be greater than 0.")
        return self._update_hp(discord_user_id, "MAX(0, hp - ?)", amount)

    def heal(self, discord_user_id: int, amount: int) -> Character:
        if amount <= 0:
            raise InvalidHitPointsError("Healing must be greater than 0.")
        return self._update_hp(discord_user_id, "MIN(max_hp, hp + ?)", amount)

    def set_hp(self, discord_user_id: int, hp: int) -> Character:
        character = self._require_character(discord_user_id)
        if not 0 <= hp <= character.max_hp:
            raise InvalidHitPointsError(
                f"HP must be between 0 and {character.max_hp} for {character.name}."
            )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE characters SET hp = ?
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (hp, discord_user_id),
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

    def _update_hp(self, discord_user_id: int, sql_expression: str, amount: int) -> Character:
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE characters SET hp = {sql_expression}
                WHERE discord_user_id = ? AND is_active = 1 AND is_archived = 0
                """,
                (amount, discord_user_id),
            )
            if cursor.rowcount == 0:
                raise CharacterNotFoundError("That Discord user does not have a character.")
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
        connection_rows = connection.execute(
            """
            SELECT id, from_room_id, to_room_id, bidirectional
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
