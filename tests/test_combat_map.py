"""Tests for the Discord combat map projection and state-driven redraws."""

import unittest
from dataclasses import replace
from io import BytesIO

from PIL import Image

from rpg_bot.combat.models import (
    CombatLandmark,
    CombatRoute,
    CombatScene,
    CombatStatus,
    CombatantKind,
    CombatantState,
    CoverLevel,
    LandmarkDistance,
)
from rpg_bot.map_renderer.combat import location_layout, render_combat_map


class CombatMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = CombatantState(
            kind=CombatantKind.CHARACTER,
            source_id="11",
            name="Sture",
            landmark_id="pillar",
            initiative_score=17,
        )
        self.enemy = CombatantState(
            kind=CombatantKind.ENEMY,
            source_id="bandit",
            name="Bandit",
            landmark_id="statue",
            initiative_score=12,
        )
        self.scene = CombatScene(
            id=22,
            guild_id=44,
            room_id="long_hall",
            status=CombatStatus.ACTIVE,
            landmarks=(
                CombatLandmark("pillar", "Stone Pillar", x=-0.7, y=0.4, cover=CoverLevel.HALF),
                CombatLandmark("statue", "Statue", x=0.5, y=-0.2, cover=CoverLevel.HALF),
                CombatLandmark("center", "Room Center", x=0.0, y=0.0),
                CombatLandmark("door", "West Door", x=-1.0, y=-0.1),
            ),
            routes=(
                CombatRoute("pillar", "center", LandmarkDistance.NEAR),
                CombatRoute("center", "statue", LandmarkDistance.FAR),
                CombatRoute("door", "center", LandmarkDistance.ADJACENT, base_blocked=True),
            ),
            combatants=(self.actor, self.enemy),
            round_number=4,
            current_turn_kind=CombatantKind.CHARACTER,
            current_turn_source_id="11",
        )

    def test_render_returns_discord_ready_png(self) -> None:
        data = render_combat_map(self.scene, "Long Hall")
        self.assertIsInstance(data, BytesIO)
        self.assertEqual(data.read(8), b"\x89PNG\r\n\x1a\n")
        data.seek(0)
        with Image.open(data) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, 1280)
            self.assertGreaterEqual(image.height, 820)

    def test_layout_keeps_locations_separate_with_negative_coordinates(self) -> None:
        positions, height = location_layout(self.scene)
        self.assertEqual(set(positions), {"pillar", "statue", "center", "door"})
        self.assertEqual(len(set(positions.values())), 4)
        self.assertGreaterEqual(height, 820)

    def test_preserves_freeform_relative_landmark_geometry(self) -> None:
        """Dashboard positions must not be rearranged to fit a tile grid."""
        positions, _ = location_layout(self.scene)
        pillar = positions["pillar"]
        statue = positions["statue"]
        center = positions["center"]
        door = positions["door"]

        # Dashboard: pillar is left/below center, statue right/above it.
        self.assertLess(pillar[0], center[0])
        self.assertGreater(pillar[1], center[1])
        self.assertGreater(statue[0], center[0])
        self.assertLess(statue[1], center[1])
        self.assertLess(door[0], pillar[0])

        # A single scale is applied to both axes (within rounding).
        dx_source = (0.5 - (-0.7)) * 1000
        dy_source = (0.4 - (-0.2)) * 700
        dx_pixels = statue[0] - pillar[0]
        dy_pixels = pillar[1] - statue[1]
        self.assertAlmostEqual(
            dx_pixels / dx_source, dy_pixels / dy_source, delta=0.005,
        )

    def test_renderer_uses_saved_coordinates_not_scene_iteration_order(self) -> None:
        positions, _ = location_layout(self.scene)
        reversed_scene = replace(
            self.scene, landmarks=tuple(reversed(self.scene.landmarks)),
        )
        reversed_positions, _ = location_layout(reversed_scene)
        self.assertEqual(positions, reversed_positions)

    def test_negative_and_out_of_room_coordinates_are_preserved(self) -> None:
        stretched = replace(
            self.scene,
            landmarks=(
                CombatLandmark("left", "Left", x=-1.0, y=0.1),
                CombatLandmark("mid", "Middle", x=0.0, y=0.4),
                CombatLandmark("right", "Right", x=2.0, y=0.7),
            ),
        )
        positions, height = location_layout(stretched)
        self.assertLess(positions["left"][0], positions["mid"][0])
        self.assertLess(positions["mid"][0], positions["right"][0])
        self.assertGreaterEqual(height, 820)
        for x, y in positions.values():
            self.assertGreaterEqual(x - 95, 0)
            self.assertLessEqual(x + 95, 1280)
            self.assertGreaterEqual(y - 47, 0)
            self.assertLessEqual(y + 47, height)

    def test_private_move_preview_highlights_reachable_and_partial_moves(self) -> None:
        normal = render_combat_map(self.scene, "Long Hall").getvalue()
        preview = render_combat_map(
            self.scene,
            "Long Hall",
            move_costs={"center": 2, "door": 5},
            movement_remaining=3,
        ).getvalue()
        self.assertNotEqual(normal, preview)
        with Image.open(BytesIO(preview)) as image:
            self.assertEqual(image.size[0], 1280)

    def test_empty_move_preview_does_not_change_public_map(self) -> None:
        first = render_combat_map(self.scene, "Long Hall").getvalue()
        second = render_combat_map(self.scene, "Long Hall").getvalue()
        self.assertEqual(first, second)

    def test_moving_character_changes_visual_map(self) -> None:
        before = render_combat_map(self.scene, "Long Hall").getvalue()
        after_scene = replace(
            self.scene,
            combatants=(replace(self.actor, landmark_id="center"), self.enemy),
        )
        after = render_combat_map(after_scene, "Long Hall").getvalue()
        self.assertNotEqual(before, after)

    def test_partial_movement_changes_visual_map(self) -> None:
        before = render_combat_map(self.scene, "Long Hall").getvalue()
        halfway = replace(
            self.actor,
            route_source_landmark_id="pillar",
            route_destination_landmark_id="center",
            route_cost=2,
            route_progress=1,
        )
        changed = replace(self.scene, combatants=(halfway, self.enemy))
        after = render_combat_map(changed, "Long Hall").getvalue()
        self.assertNotEqual(before, after)

    def test_blocked_route_and_state_changes_render(self) -> None:
        without_block = replace(
            self.scene,
            routes=tuple(replace(route, base_blocked=False) for route in self.scene.routes),
        )
        self.assertNotEqual(
            render_combat_map(self.scene, "Long Hall").getvalue(),
            render_combat_map(without_block, "Long Hall").getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
