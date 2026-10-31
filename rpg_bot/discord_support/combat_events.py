"""Combat event presentation and durable Discord archive delivery.

CombatRepository is the source of truth. This module never invents combat
actions and never attributes an NPC action to the Discord user controlling it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import sqlite3

import discord

from ..combat.models import CombatLogEntry, CombatantKind, CombatScene


LOGGER = logging.getLogger(__name__)
COMBAT_LOG_CHANNEL_NAME = "combat-log"
TURN_MARKERS = frozenset({"turn_started", "turn_changed", "turn_rewound"})
# Only resolved world events appear to players; DM/editor commands and
# bookkeeping remain in the database for administrative inspection.
PUBLIC_EVENTS = frozenset({
    "combatant_moved", "combatant_dashed", "defend_prepared",
    "attack_resolved", "enemy_attack_resolved", "item_used",
    "combatant_defeated", "combatant_downed", "combatant_died",
    "combatant_stabilized", "death_save_success", "death_save_failed",
    "combatant_joined", "combatant_removed",
})


def _safe(text: str) -> str:
    return discord.utils.escape_markdown(discord.utils.escape_mentions(text))


def event_lines(entries: tuple[CombatLogEntry, ...] | list[CombatLogEntry]) -> list[str]:
    return [
        _safe(entry.message)
        for entry in entries
        if entry.event_type in PUBLIC_EVENTS
    ]


def current_turn_events(scene: CombatScene) -> list[str]:
    """Show only events after the current turn marker, not previous turns."""
    last_marker = -1
    for index, entry in enumerate(scene.log_entries):
        if entry.event_type in TURN_MARKERS:
            last_marker = index
    if last_marker == -1 or scene.current_combatant() is None:
        return []
    return event_lines(scene.log_entries[last_marker + 1:])


@dataclass(frozen=True)
class ArchivedTurn:
    scene_id: int
    round_number: int
    actor_name: str
    actor_kind: CombatantKind | None
    lines: tuple[str, ...]
    # The first event of the next turn (or combat_ended). Saving this marker
    # after sending lets a restarted bot resume without replaying prior turns.
    resume_at_id: int


def closed_turns(entries: list[CombatLogEntry], scene_id: int) -> list[ArchivedTurn]:
    """Split the authoritative event stream at turn boundaries."""
    result: list[ArchivedTurn] = []
    started: CombatLogEntry | None = None
    actions: list[CombatLogEntry] = []
    for entry in entries:
        closing = entry.event_type in TURN_MARKERS or entry.event_type == "combat_ended"
        if closing:
            if started is not None:
                result.append(ArchivedTurn(
                    scene_id=scene_id,
                    round_number=started.round_number,
                    actor_name=started.actor_name or "Unknown combatant",
                    actor_kind=started.actor_kind,
                    lines=tuple(event_lines(actions)),
                    resume_at_id=entry.id,
                ))
            started = entry if entry.event_type in TURN_MARKERS else None
            actions = []
        elif started is not None:
            actions.append(entry)
    return result


def archive_embeds(turn: ArchivedTurn) -> list[discord.Embed]:
    lines = list(turn.lines) or ["No actions recorded."]
    # Discord embed descriptions are limited to 4096 characters.
    parts: list[str] = []
    chunk = ""
    for line in lines:
        item = f"• {line}"
        if len(item) > 3500:
            item = item[:3497] + "..."
        if chunk and len(chunk) + len(item) + 1 > 3500:
            parts.append(chunk)
            chunk = ""
        chunk += ("\n" if chunk else "") + item
    if chunk:
        parts.append(chunk)
    result = []
    for number, part in enumerate(parts, start=1):
        title = f"Round {turn.round_number} · {_safe(turn.actor_name)}"
        if len(parts) > 1:
            title += f" ({number}/{len(parts)})"
        embed = discord.Embed(
            title=title[:256],
            description=part,
            colour=discord.Colour.from_rgb(93, 120, 145),
        )
        embed.set_footer(text=f"Combat scene #{turn.scene_id}")
        result.append(embed)
    return result


class CombatEventArchiveStore:
    """Durable per-scene Discord delivery checkpoint in the combat database."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS combat_discord_archive_progress (
                    guild_id INTEGER NOT NULL,
                    scene_id INTEGER NOT NULL,
                    resume_at_id INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, scene_id)
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def ensure_scene(self, guild_id: int, scene_id: int) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO combat_discord_archive_progress "
                "(guild_id, scene_id, resume_at_id) VALUES (?, ?, 0)",
                (guild_id, scene_id),
            )

    def progress(self, guild_id: int, scene_id: int) -> int:
        with self._connect() as db:
            row = db.execute(
                "SELECT resume_at_id FROM combat_discord_archive_progress "
                "WHERE guild_id = ? AND scene_id = ?",
                (guild_id, scene_id),
            ).fetchone()
        return int(row["resume_at_id"]) if row else 0

    def mark_sent(self, guild_id: int, scene_id: int, resume_at_id: int) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO combat_discord_archive_progress
                    (guild_id, scene_id, resume_at_id)
                VALUES (?, ?, ?)
                ON CONFLICT (guild_id, scene_id) DO UPDATE SET
                    resume_at_id = MAX(resume_at_id, excluded.resume_at_id)
                """,
                (guild_id, scene_id, resume_at_id),
            )

    def entries_from(self, scene_id: int, resume_at_id: int) -> list[CombatLogEntry]:
        # Do not use CombatScene.log_entries here; the dashboard only loads
        # the 100 most recent events, which would silently lose archive data.
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, round_number, event_type, actor_kind,
                       actor_source_id, actor_name, message, created_at
                FROM combat_log_entries
                WHERE scene_id = ? AND id >= ?
                ORDER BY id
                """,
                (scene_id, resume_at_id),
            ).fetchall()
        return [
            CombatLogEntry(
                id=int(row["id"]),
                round_number=int(row["round_number"]),
                event_type=row["event_type"],
                message=row["message"],
                created_at=row["created_at"],
                actor_kind=CombatantKind(row["actor_kind"])
                if row["actor_kind"] else None,
                actor_source_id=row["actor_source_id"],
                actor_name=row["actor_name"],
            )
            for row in rows
        ]


async def ensure_combat_log_channel(guild):
    for channel in getattr(guild, "text_channels", ()):
        if getattr(channel, "name", "").casefold() == COMBAT_LOG_CHANNEL_NAME:
            return channel

    bot_member = getattr(guild, "me", None)
    if (
        bot_member is None
        or not getattr(bot_member.guild_permissions, "manage_channels", False)
    ):
        LOGGER.warning(
            "Unable to create #%s in guild %s: Manage Channels missing",
            COMBAT_LOG_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None
    try:
        return await guild.create_text_channel(
            COMBAT_LOG_CHANNEL_NAME,
            topic="Permanent record of completed in-world combat turns.",
            reason="Permanent combat turn archive",
        )
    except discord.HTTPException:
        LOGGER.exception(
            "Unable to create #%s in guild %s",
            COMBAT_LOG_CHANNEL_NAME,
            getattr(guild, "id", "unknown"),
        )
        return None
