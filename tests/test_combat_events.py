"""Combat event stream, live turn presentation and durable archival."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from rpg_bot.combat.models import (
    CombatLogEntry, CombatScene, CombatStatus, CombatantKind, CombatantState,
)
from rpg_bot.discord_support.combat_events import (
    CombatEventArchiveStore,
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


class CombatEventArchiveStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "rpg.db"
        with sqlite3.connect(self.path) as db:
            db.executescript(
                """
                CREATE TABLE combat_scenes (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL
                );
                CREATE TABLE combat_log_entries (
                    id INTEGER PRIMARY KEY,
                    scene_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_kind TEXT,
                    actor_source_id TEXT,
                    actor_name TEXT,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO combat_scenes VALUES (22, 'ended');
                INSERT INTO combat_log_entries VALUES
                    (1,22,1,'turn_started','enemy','bandit-1','Bandit',
                     'Bandit turn began','2026-10-31T10:00:00Z'),
                    (2,22,1,'combatant_moved','enemy','bandit-1','Bandit',
                     'Bandit moved','2026-10-31T10:01:00Z'),
                    (3,22,1,'turn_started','character','11','Sture',
                     'Sture turn began','2026-10-31T10:02:00Z'),
                    (4,22,1,'combatant_dashed','character','11','Sture',
                     'Sture dashed','2026-10-31T10:03:00Z'),
                    (5,22,1,'combat_ended',NULL,NULL,NULL,
                     'Combat ended','2026-10-31T10:04:00Z');
                """
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_checkpoint_survives_restart_and_advances_monotonically(self) -> None:
        first = CombatEventArchiveStore(self.path)
        first.ensure_scene(44, 22)
        self.assertEqual(first.pending_scenes(44), [22])
        turns = closed_turns(first.entries_from(22, 0), 22)
        self.assertEqual(len(turns), 2)
        first.mark_sent(44, 22, turns[0].resume_at_id)
        second = CombatEventArchiveStore(self.path)
        self.assertEqual(second.progress(44, 22), 3)
        self.assertEqual(
            [t.actor_name for t in closed_turns(second.entries_from(22, 3), 22)],
            ["Sture"],
        )
        second.mark_sent(44, 22, 5)
        second.mark_sent(44, 22, 3)
        self.assertEqual(second.progress(44, 22), 5)
        self.assertEqual(second.pending_scenes(44), [])

    def test_read_is_not_capped_to_scene_last_100_events(self) -> None:
        store = CombatEventArchiveStore(self.path)
        with sqlite3.connect(self.path) as db:
            for offset in range(105):
                db.execute(
                    "INSERT INTO combat_log_entries VALUES "
                    "(?,?,?,?,?,?,?,?,?)",
                    (
                        10 + offset, 22, 1, "combatant_moved", "enemy",
                        "bandit-1", "Bandit", f"Bandit moved {offset}",
                        "2026-10-31T10:05:00Z",
                    ),
                )
        self.assertGreater(len(store.entries_from(22, 0)), 100)


if __name__ == "__main__":
    unittest.main()
