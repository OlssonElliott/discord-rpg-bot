"""Character identity presentation shared by Discord adapters."""

from pathlib import Path

import discord

from ..models import Character
from ..portraits import CharacterPortraitStore, DEFAULT_DM_PORTRAIT_KEY


def apply_character_identity(
    embed: discord.Embed,
    character: Character | None,
    portrait_store: CharacterPortraitStore,
    dm_portrait_key: str | None = None,
) -> Path | None:
    if character is None:
        path = portrait_store.path_for(dm_portrait_key)
        if path is None:
            path = portrait_store.path_for(DEFAULT_DM_PORTRAIT_KEY)
        name = "Dungeon Master"
    else:
        path = portrait_store.path_for(character.portrait_key)
        name = character.name
    embed.set_author(name=name)
    if path is not None:
        embed.set_thumbnail(url=f"attachment://{portrait_attachment_name(path)}")
    return path


def portrait_attachment_name(path: Path) -> str:
    return f"character_portrait{path.suffix.lower()}"
