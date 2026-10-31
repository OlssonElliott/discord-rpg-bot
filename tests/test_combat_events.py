"""Combat event stream, live turn presentation and durable archival."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from rpg_bot.commands.combat import CombatCommands, combat_scene_embed

from rpg_bot.combat.models import (
    CombatLogEntry, CombatScene, CombatStatus, CombatantKind, CombatantState,
)
from rpg_bot.discord_support.combat_events import (
    CombatEventReader,
    archive_embeds,
    closed_turns,
    current_turn_events,
)


def event(
    event_id: int,
    event_type: str,
    message: str,
    actor_name: str = "Bandit",
    round_number: int = 1,
) -> CombatLogEntry:
    return CombatLogEntry(
        id=event_id,
        round_number=round_number,
        event_type=event_type,
        message=message,
        created_at="2026-10-31T10:00:00Z",
        actor_kind=CombatantKind.ENEMY,
        actor_source_id="bandit-1",
        actor_name=actor_name,
    )


class CombatEventPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [
            event(1, "combat_started", "Combat started"),
            event(2, "turn_started", "Bandit's turn began"),
            event(3, "combatant_moved", "Bandit moved to Stone Pillar"),
            event(4, "enemy_attack_resolved", "Bandit attacked Sture for 6 damage"),
            event(5, "turn_started", "Sture's turn began", "Sture"),
            event(6, "combatant_dashed", "Sture Dashed", "Sture"),
            event(7, "turn_started", "Bandit's turn began", "Bandit", 2),
        ]

    def test_live_view_only_shows_events_from_current_turn(self) -> None:
        scene = CombatScene(
            id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            combatants=(
                CombatantState(CombatantKind.CHARACTER, "11", "Sture", "center"),
            ),
            current_turn_kind=CombatantKind.CHARACTER,
            current_turn_source_id="11",
            log_entries=tuple(self.entries[:6]),
        )
        self.assertEqual(current_turn_events(scene), ["Sture Dashed"])
        # A completed turn is replaced by the next actor's empty live stream.
        later = CombatScene(
            id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            combatants=(
                CombatantState(CombatantKind.ENEMY, "bandit-1", "Bandit", "center"),
            ),
            round_number=2,
            current_turn_kind=CombatantKind.ENEMY,
            current_turn_source_id="bandit-1",
            log_entries=tuple(self.entries),
        )
        self.assertEqual(current_turn_events(later), [])

    def test_archive_splits_on_turn_markers_and_uses_actor_identity(self) -> None:
        turns = closed_turns(self.entries, scene_id=22)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].actor_name, "Bandit")
        self.assertEqual(turns[0].round_number, 1)
        self.assertEqual(turns[0].resume_at_id, 5)
        self.assertEqual(turns[0].lines, (
            "Bandit moved to Stone Pillar",
            "Bandit attacked Sture for 6 damage",
        ))
        self.assertEqual(turns[1].actor_name, "Sture")
        self.assertEqual(turns[1].resume_at_id, 7)

    def test_no_unfinished_turn_is_archived(self) -> None:
        self.assertEqual(closed_turns(self.entries[:4], scene_id=22), [])

    def test_combat_end_closes_final_turn(self) -> None:
        turns = closed_turns(
            self.entries[:6] + [event(7, "combat_ended", "Combat ended", "")],
            scene_id=22,
        )
        self.assertEqual(turns[-1].actor_name, "Sture")
        self.assertEqual(turns[-1].resume_at_id, 7)

    def test_archive_title_names_in_world_actor_not_dm(self) -> None:
        turn = closed_turns(self.entries, scene_id=22)[0]
        embed = archive_embeds(turn)[0]
        self.assertIn("Bandit", embed.title)
        self.assertNotIn("DM", embed.title)
        self.assertIn("Bandit attacked Sture", embed.description)

    def test_admin_turn_change_is_not_a_public_action(self) -> None:
        entries = [
            event(1, "turn_started", "Bandit's turn began"),
            event(2, "turn_changed", "DM changed turn to Sture", "Sture"),
            event(3, "combatant_moved", "Sture moved to the Door", "Sture"),
            event(4, "turn_started", "Bandit's turn began", "Bandit"),
        ]
        turns = closed_turns(entries, scene_id=22)
        self.assertEqual(turns[0].lines, ())
        self.assertEqual(turns[1].lines, ("Sture moved to the Door",))


class CombatEventReaderTests(unittest.TestCase):
    def test_read_full_event_history_without_scene_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "combat.db"
            with sqlite3.connect(path) as db:
                db.execute(
                    """
                    CREATE TABLE combat_log_entries (
                        id INTEGER PRIMARY KEY, scene_id INTEGER NOT NULL,
                        round_number INTEGER NOT NULL, event_type TEXT NOT NULL,
                        actor_kind TEXT, actor_source_id TEXT, actor_name TEXT,
                        message TEXT NOT NULL, created_at TEXT NOT NULL
                    )
                    """
                )
                db.executemany(
                    "INSERT INTO combat_log_entries VALUES (?,?,?,?,?,?,?,?,?)",
                    [
                        (index, 22, 1, "combatant_moved", "enemy", "bandit",
                         "Bandit", f"Bandit moved {index}", "2026-10-31T10:00:00Z")
                        for index in range(1, 121)
                    ],
                )
            reader = CombatEventReader(path)
            self.assertEqual(len(reader.entries_from(22, 0)), 120)
            newer = reader.entries_from(22, 117)
            self.assertEqual([event.id for event in newer], [117, 118, 119, 120])


class CombatOneChannelPresentationTests(unittest.TestCase):
    def test_summary_shows_actions_by_in_world_actor(self) -> None:
        entries = [
            event(1, "turn_started", "Bandit began"),
            event(2, "enemy_attack_resolved", "Bandit attacks Sture"),
            event(3, "turn_started", "Sture began", "Sture"),
        ]
        turns = closed_turns(entries, scene_id=22)
        self.assertEqual(len(turns), 1)
        summary = archive_embeds(turns[0])[0]
        self.assertIn("Bandit", summary.title)
        self.assertIn("Bandit attacks", summary.description)

    def test_live_combat_card_shows_events_and_clears_next_turn(self) -> None:
        actions = (
            event(1, "turn_started", "Bandit began"),
            event(2, "enemy_attack_resolved", "Bandit attacked Sture"),
        )
        actor = CombatantState(CombatantKind.ENEMY, "bandit-1", "Bandit", "center")
        scene = CombatScene(
            id=22, guild_id=44, room_id="hall", status=CombatStatus.ACTIVE,
            combatants=(actor,),
            current_turn_kind=CombatantKind.ENEMY,
            current_turn_source_id="bandit-1",
            log_entries=actions,
        )
        embed = combat_scene_embed(scene, "Long Hall")
        self.assertEqual(
            [field.name for field in embed.fields],
            ["Turn order", "Current turn · Bandit"],
        )
        self.assertIn("Bandit attacked Sture", embed.fields[1].value)

        from dataclasses import replace
        cleared = replace(
            scene,
            log_entries=actions + (
                event(3, "turn_started", "Bandit began again"),
            ),
        )
        self.assertIn(
            "Waiting for an action",
            combat_scene_embed(cleared, "Long Hall").fields[1].value,
        )


if __name__ == "__main__":
    unittest.main()
