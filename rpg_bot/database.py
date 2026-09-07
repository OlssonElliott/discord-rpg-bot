"""SQLite persistence for RPG characters."""

from contextlib import contextmanager
from collections.abc import Iterator, Mapping
from pathlib import Path
import sqlite3

from .dice_visuals import (
    DEFAULT_DICE_COLOR,
    DEFAULT_DICE_EDGE_COLOR,
    DEFAULT_DICE_NUMBER_COLOR,
    normalize_dice_color,
)
from .models import Character, Stance


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    discord_user_id INTEGER PRIMARY KEY,
                    dice_color TEXT NOT NULL,
                    dice_edge_color TEXT NOT NULL DEFAULT '#303030',
                    dice_number_color TEXT NOT NULL DEFAULT '#101010'
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
                        is_active, is_archived
                    )
                    SELECT discord_user_id, name, hp, max_hp, stance,
                           lineage, race, age, gender,
                           strength, dexterity, arcana, vitality, insight, personality,
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
    ) -> Character:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Character name cannot be empty.")
        if len(clean_name) > 100:
            raise ValueError("Character name cannot be longer than 100 characters.")
        if max_hp <= 0:
            raise InvalidHitPointsError("Maximum HP must be greater than 0.")

        try:
            with self._connect() as connection:
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
                        is_active, is_archived
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
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
                    ),
                )
                character_id = cursor.lastrowid
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
                       is_active, is_archived
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
                       is_active, is_archived
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
                       is_active, is_archived
                FROM characters
                WHERE discord_user_id = ? AND is_archived = 0
                ORDER BY is_active DESC, id ASC
                """,
                (discord_user_id,),
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
            connection.execute(
                "UPDATE characters SET is_active = 0 WHERE discord_user_id = ?",
                (discord_user_id,),
            )
            connection.execute(
                "UPDATE characters SET is_active = 1 WHERE id = ?",
                (character_id,),
            )
        character = self.get_character(discord_user_id)
        if character is None:
            raise RuntimeError("Selected character could not be loaded.")
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
        archived = self.get_character_by_id(
            discord_user_id, character_id, include_archived=True
        )
        if archived is None:
            raise RuntimeError("Archived character could not be loaded.")
        return archived

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
        )
