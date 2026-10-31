"""Read authoritative combat events and format in-world turn summaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

import discord

from ..combat.models import CombatLogEntry, CombatantKind, CombatScene


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
    start_marker_id: int
    round_number: int
    actor_name: str
    actor_kind: CombatantKind | None
    lines: tuple[str, ...]
    # The next turn marker (or combat_ended). The publisher uses stable
    # start_marker_id/page identifiers to reconcile Discord delivery.
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
                    start_marker_id=started.id,
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
        embed.set_footer(
            text=(
                f"Combat scene #{turn.scene_id} · "
                f"Turn #{turn.start_marker_id} · summary {number}/{len(parts)}"
            )
        )
        result.append(embed)
    return result


class CombatEventReader:
    """Read the full combat event log without the scene's 100-entry limit."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

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

