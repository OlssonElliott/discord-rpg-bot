from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageChops, ImageDraw

from rpg_bot.world.dungeon import FocusedRoomView, KnowledgeState
from rpg_bot.media.room_images import InvalidRoomImageError, RoomImageStore
from rpg_bot.media.room_scene import (
    INFO_BOUNDS,
    PANEL_SIZE,
    ROOM_PANEL_PATH,
    SCENE_APERTURE_BOUNDS,
    SCENE_LAYER_BOUNDS,
    _loaded_room_panel,
    _list_lines,
    _scene_aperture_mask,
    _summarize,
    _wrap_text,
    render_room_card,
)


def image_bytes(
    size: tuple[int, int] = (800, 450), image_format: str = "PNG"
) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "purple").save(output, format=image_format)
    return output.getvalue()


class RoomImageStoreTests(unittest.TestCase):
    def test_valid_image_is_normalized_to_generated_webp_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RoomImageStore(directory)

            key = store.save(image_bytes(), "image/png")
            path = store.path_for(key)

            self.assertRegex(key, r"^[0-9a-f]{32}\.webp$")
            self.assertEqual(path, Path(directory) / key)
            assert path is not None
            with Image.open(path) as stored:
                self.assertEqual(stored.format, "WEBP")
                self.assertEqual(stored.size, (800, 450))

    def test_mime_mismatch_oversize_and_traversal_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RoomImageStore(directory)
            with self.assertRaisesRegex(InvalidRoomImageError, "content type"):
                store.save(image_bytes(), "image/jpeg")
            with self.assertRaisesRegex(InvalidRoomImageError, "filename must end"):
                store.save(image_bytes(), "image/png", "room.exe")
            with self.assertRaisesRegex(InvalidRoomImageError, "at most 8 MB"):
                store.save(b"x" * (8 * 1024 * 1024 + 1), "image/png")
            self.assertIsNone(store.path_for("../outside.webp"))


class RoomCardRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.scene_path = Path(self.temporary_directory.name) / "scene.png"
        self.scene_path.write_bytes(image_bytes())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_full_panel_scene_and_lower_information_are_preserved(self) -> None:
        self.assertTrue(ROOM_PANEL_PATH.is_file())
        view = FocusedRoomView(
            "next",
            KnowledgeState.VISITED,
            "next",
            "next location",
            visible_characters=("Bobby",),
            visible_items=("key", "Rusted Knight Harness"),
        )

        rendered = render_room_card(view, is_current=True, scene_path=self.scene_path)

        self.assertIsNotNone(rendered)
        assert rendered is not None
        with Image.open(rendered) as card:
            self.assertEqual(card.format, "WEBP")
            self.assertEqual(card.size, PANEL_SIZE)
            scene_center = (
                (SCENE_APERTURE_BOUNDS[0] + SCENE_APERTURE_BOUNDS[2]) // 2,
                (SCENE_APERTURE_BOUNDS[1] + SCENE_APERTURE_BOUNDS[3]) // 2,
            )
            self.assertEqual(card.getpixel(scene_center), (128, 0, 128, 255))
            self.assertEqual(card.getpixel((0, 0))[3], 0)
            panel = _loaded_room_panel()
            assert panel is not None
            self.assertEqual(card.getpixel((724, 120)), (128, 0, 128, 255))
            # The scene opening is rectangular: no centre ornaments or corner
            # flourishes intrude into the image anymore.
            self.assertEqual(card.getpixel((724, 590)), (128, 0, 128, 255))
            self.assertEqual(card.getpixel((690, 590)), (128, 0, 128, 255))
            self.assertEqual(card.getpixel((758, 590)), (128, 0, 128, 255))
            self.assertLess(SCENE_LAYER_BOUNDS[0], SCENE_APERTURE_BOUNDS[0])
            self.assertLess(SCENE_LAYER_BOUNDS[1], SCENE_APERTURE_BOUNDS[1])
            self.assertGreater(SCENE_LAYER_BOUNDS[2], SCENE_APERTURE_BOUNDS[2])
            self.assertGreater(SCENE_LAYER_BOUNDS[3], SCENE_APERTURE_BOUNDS[3])
            untouched_border = (80, 300)
            self.assertEqual(
                card.getpixel(untouched_border),
                panel.getpixel(untouched_border),
            )
            difference = ImageChops.difference(card, panel)
            self.assertIsNotNone(difference.crop(INFO_BOUNDS).getbbox())

    def test_scene_aperture_is_a_clean_rectangle(self) -> None:
        mask = _scene_aperture_mask()
        try:
            # All four inner corners and both former ornament positions are
            # part of one uninterrupted rectangular scene opening.
            self.assertGreater(mask.getpixel((120, 120)), 250)
            self.assertGreater(mask.getpixel((180, 130)), 250)
            self.assertGreater(mask.getpixel((1328, 125)), 250)
            self.assertGreater(mask.getpixel((1270, 130)), 250)
            self.assertGreater(mask.getpixel((120, 620)), 250)
            self.assertGreater(mask.getpixel((1328, 620)), 250)
            self.assertGreater(mask.getpixel((724, 120)), 250)
            self.assertGreater(mask.getpixel((650, 120)), 250)
            self.assertGreater(mask.getpixel((724, 590)), 250)
            self.assertGreater(mask.getpixel((690, 590)), 250)
            self.assertGreater(mask.getpixel((758, 590)), 250)
            self.assertLess(mask.getpixel((112, 110)), 5)
            self.assertLess(mask.getpixel((1336, 630)), 5)
        finally:
            mask.close()

    def test_known_room_never_uses_supplied_scene_or_hidden_details(self) -> None:
        known = FocusedRoomView("study", KnowledgeState.KNOWN, "Forgotten Study")

        with_scene = render_room_card(
            known, is_current=False, scene_path=self.scene_path
        )
        without_scene = render_room_card(known, is_current=False)

        assert with_scene is not None and without_scene is not None
        self.assertEqual(with_scene.getvalue(), without_scene.getvalue())

    def test_fallback_inspected_state_and_overflow_render_inside_fixed_card(self) -> None:
        view = FocusedRoomView(
            "archive",
            KnowledgeState.VISITED,
            "The Extremely Long and Entirely Forgotten Royal Archive",
            "A " + "very long remembered description " * 30,
            visible_characters=tuple(f"Character {index}" for index in range(8)),
            visible_entities=tuple(f"Creature {index}" for index in range(8)),
            visible_items=tuple(f"Item {index}" for index in range(8)),
        )

        current = render_room_card(view, is_current=True)
        inspected = render_room_card(view, is_current=False)

        assert current is not None and inspected is not None
        self.assertNotEqual(current.getvalue(), inspected.getvalue())
        with Image.open(inspected) as card:
            self.assertEqual(card.size, PANEL_SIZE)

        canvas = Image.new("RGB", (300, 100))
        draw = ImageDraw.Draw(canvas)
        lines = _wrap_text(
            draw,
            "many words that cannot all fit in this narrow box",
            _loaded_test_font(),
            90,
            max_lines=2,
        )
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertEqual(_summarize(tuple("ABCDE"), limit=1), ("A", "+ 4 more"))
        item_lines = _list_lines(
            draw,
            ("key", "Rusted Knight Harness"),
            _loaded_test_font(),
            90,
            max_lines=5,
        )
        self.assertEqual(item_lines[0], "key")
        self.assertNotIn("…", " ".join(item_lines))


def _loaded_test_font():
    from PIL import ImageFont

    return ImageFont.load_default()


if __name__ == "__main__":
    unittest.main()
