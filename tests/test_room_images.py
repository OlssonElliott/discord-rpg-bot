from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from rpg_bot.room_images import InvalidRoomImageError, RoomImageStore
from rpg_bot.room_scene_renderer import (
    PANEL_CROP,
    ROOM_PANEL_PATH,
    render_room_scene_panel,
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

    def test_panel_asset_frames_a_room_scene(self) -> None:
        self.assertTrue(ROOM_PANEL_PATH.is_file())
        with tempfile.TemporaryDirectory() as directory:
            scene_path = Path(directory) / "scene.png"
            scene_path.write_bytes(image_bytes())

            rendered = render_room_scene_panel(scene_path)

            self.assertIsNotNone(rendered)
            assert rendered is not None
            with Image.open(rendered) as panel:
                self.assertEqual(panel.format, "WEBP")
                self.assertEqual(panel.size, (PANEL_CROP[2], PANEL_CROP[3]))


if __name__ == "__main__":
    unittest.main()
