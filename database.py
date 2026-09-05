"""SQLite persistence for RPG characters."""

from pathlib import Path
import sqlite3

from models import Character, Stance


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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS characters (
                    discord_user_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    hp INTEGER NOT NULL CHECK (hp >= 0 AND hp <= max_hp),
                    max_hp INTEGER NOT NULL CHECK (max_hp > 0),
                    stance TEXT NOT NULL CHECK (
                        stance IN ('steady', 'bad_stance', 'prone')
                    )
                )
                """
            )

    def create_character(self, discord_user_id: int, name: str, max_hp: int) -> Character:
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
                    INSERT INTO characters (discord_user_id, name, hp, max_hp, stance)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (discord_user_id, clean_name, max_hp, max_hp, Stance.STEADY.value),
                )
        except sqlite3.IntegrityError as error:
            raise CharacterAlreadyExistsError(
                "That Discord user already has a character."
            ) from error

        return Character(discord_user_id, clean_name, max_hp, max_hp, Stance.STEADY)

    def get_character(self, discord_user_id: int) -> Character | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT discord_user_id, name, hp, max_hp, stance
                FROM characters
                WHERE discord_user_id = ?
                """,
                (discord_user_id,),
            ).fetchone()
        return self._to_character(row) if row else None

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
                "UPDATE characters SET hp = ? WHERE discord_user_id = ?",
                (hp, discord_user_id),
            )
        return self._require_character(discord_user_id)

    def set_stance(self, discord_user_id: int, stance: Stance) -> Character:
        self._require_character(discord_user_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE characters SET stance = ? WHERE discord_user_id = ?",
                (stance.value, discord_user_id),
            )
        return self._require_character(discord_user_id)

    def _update_hp(self, discord_user_id: int, sql_expression: str, amount: int) -> Character:
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE characters SET hp = {sql_expression} WHERE discord_user_id = ?",
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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _to_character(row: sqlite3.Row) -> Character:
        return Character(
            discord_user_id=row["discord_user_id"],
            name=row["name"],
            hp=row["hp"],
            max_hp=row["max_hp"],
            stance=Stance(row["stance"]),
        )
