"""Character schema creation and migration helpers."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from ...inventory import DEFAULT_CLOTHING_TEMPLATE_ID


class DatabaseCharacterSchemaMixin:
    """Create and migrate character-related database tables."""

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
                hunger INTEGER NOT NULL DEFAULT 0 CHECK (hunger BETWEEN 0 AND 100),
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
                    hunger, portrait_key, current_room_id, is_active, is_archived
                )
                SELECT
                    id, discord_user_id, name, hp, max_hp, stance,
                    lineage, race, age, gender,
                    strength, dexterity, arcana, vitality, insight, personality,
                    hunger, portrait_key, current_room_id, is_active, is_archived
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
                "hunger": (
                    "ALTER TABLE characters ADD COLUMN hunger INTEGER NOT NULL "
                    "DEFAULT 0 CHECK (hunger BETWEEN 0 AND 100)"
                ),
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
                        hunger, portrait_key,
                        is_active, is_archived
                    )
                    SELECT discord_user_id, name, hp, max_hp, stance,
                           lineage, race, age, gender,
                           strength, dexterity, arcana, vitality, insight, personality,
                           hunger, portrait_key,
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
