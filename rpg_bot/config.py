"""Environment-based bot configuration."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

from .dice_assets import DEFAULT_DICE_THEME, normalize_dice_theme


@dataclass(frozen=True, slots=True)
class Config:
    discord_token: str
    dm_role_name: str = "DM"
    database_path: str = "rpg_bot.db"
    character_media_path: str = "data/characters"
    discord_guild_id: int | None = None
    dice_theme: str = DEFAULT_DICE_THEME

    def __post_init__(self) -> None:
        object.__setattr__(self, "dice_theme", normalize_dice_theme(self.dice_theme))

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "DISCORD_TOKEN is not configured. Copy .env.example to .env and add the token."
            )

        guild_id_text = os.getenv("DISCORD_GUILD_ID", "").strip()
        try:
            guild_id = int(guild_id_text) if guild_id_text else None
        except ValueError as error:
            raise ValueError("DISCORD_GUILD_ID must be a numeric Discord server ID.") from error

        return cls(
            discord_token=token,
            dm_role_name=os.getenv("DM_ROLE_NAME", "DM").strip() or "DM",
            database_path=os.getenv("DATABASE_PATH", "rpg_bot.db").strip() or "rpg_bot.db",
            character_media_path=(
                os.getenv("CHARACTER_MEDIA_PATH", "data/characters").strip()
                or "data/characters"
            ),
            discord_guild_id=guild_id,
            dice_theme=os.getenv("DICE_THEME", DEFAULT_DICE_THEME),
        )
