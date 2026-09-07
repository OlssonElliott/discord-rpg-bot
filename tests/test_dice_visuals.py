import tempfile
import unittest
from pathlib import Path

from PIL import Image

from rpg_bot.dice_visuals import (
    D20AnimationRenderer,
    InvalidDiceColorError,
    normalize_dice_color,
)


class DiceVisualTests(unittest.TestCase):
    @staticmethod
    def create_master(path: Path, dark: int = 64, light: int = 192) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        first = Image.new("RGBA", (2, 2), (dark, dark, dark, 255))
        first.putpixel((0, 0), (0, 0, 0, 0))
        second = Image.new("RGBA", (2, 2), (light, light, light, 255))
        second.putpixel((0, 0), (0, 0, 0, 0))
        first.save(
            path,
            save_all=True,
            append_images=[second],
            duration=[200, 300],
            loop=0,
        )

    def test_colors_are_normalized_and_validated(self) -> None:
        self.assertEqual(normalize_dice_color("7a2eff"), "#7A2EFF")
        self.assertEqual(normalize_dice_color(" #00BfFf "), "#00BFFF")
        for color in ("purple", "#12345", "#GG00FF", "##123456"):
            with self.subTest(color=color):
                with self.assertRaises(InvalidDiceColorError):
                    normalize_dice_color(color)

    def test_tint_preserves_luminance_transparency_and_colored_pixels(self) -> None:
        source = Image.new("RGBA", (5, 1))
        source.putdata(
            [
                (0, 0, 0, 0),
                (64, 64, 64, 255),
                (128, 128, 128, 255),
                (255, 255, 255, 255),
                (255, 0, 0, 255),
            ]
        )

        tinted = D20AnimationRenderer._tint_frame(source, "#7A2EFF")

        self.assertEqual(
            list(tinted.getdata()),
            [
                (0, 0, 0, 0),
                (58, 25, 117, 255),
                (86, 39, 170, 255),
                (142, 66, 255, 255),
                (255, 0, 0, 255),
            ],
        )

    def test_render_uses_a_fresh_disk_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            self.create_master(assets / "themes" / "classic" / "d20_17.gif")
            renderer = D20AnimationRenderer(assets, theme="classic")

            generated = renderer.render(17, "#7A2EFF")
            self.assertIsNotNone(generated)
            self.assertTrue(generated.path.is_file())
            self.assertTrue(generated.result_image_path.is_file())
            self.assertAlmostEqual(generated.duration_seconds, 0.5)
            with Image.open(generated.path) as tinted:
                self.assertEqual(tinted.convert("RGBA").getpixel((0, 0))[3], 0)
                self.assertNotIn("loop", tinted.info)
            with Image.open(generated.result_image_path) as result_image:
                self.assertEqual(result_image.size, (160, 160))
                self.assertIsNotNone(result_image.convert("RGBA").getchannel("A").getbbox())
            modified_time = generated.path.stat().st_mtime_ns

            cached = renderer.render(17, "7a2eff")
            self.assertEqual(cached.path, generated.path)
            self.assertEqual(cached.result_image_path, generated.result_image_path)
            self.assertEqual(cached.path.stat().st_mtime_ns, modified_time)
            self.assertAlmostEqual(cached.duration_seconds, 0.5)

    def test_single_die_glow_is_rendered_and_has_its_own_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            self.create_master(assets / "themes" / "classic" / "d20_20.gif")
            renderer = D20AnimationRenderer(assets, theme="classic")

            plain = renderer.render(20, "#7A2EFF")
            glowing = renderer.render(20, "#7A2EFF", glow_color="#2ECC71")

            self.assertNotEqual(plain.path, glowing.path)
            self.assertIn("glow_v4_2ECC71", glowing.path.name)
            with Image.open(glowing.result_image_path) as result_image:
                rgba = result_image.convert("RGBA")
                self.assertGreater(rgba.getchannel("A").getbbox()[2], 0)

    def test_selected_theme_resolves_its_asset_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            master = assets / "themes" / "cartoon" / "d20_17.gif"
            self.create_master(master)
            renderer = D20AnimationRenderer(assets, theme="cartoon")

            resolved = renderer.resolve_master(17)
            generated = renderer.render(17, "#7A2EFF", resolved)

            self.assertEqual(resolved.path, master)
            self.assertEqual(resolved.theme, "cartoon")
            self.assertEqual(
                generated.path,
                assets
                / "cache"
                / "v2"
                / "cartoon"
                / "7A2EFF"
                / "303030"
                / "101010"
                / "d20_17.gif",
            )

    def test_non_d20_uses_its_own_assets_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dice = Path(directory) / "dice"
            d20_directory = dice / "d20"
            master = dice / "d6" / "themes" / "cartoon" / "d6_4.gif"
            self.create_master(master)
            renderer = D20AnimationRenderer(d20_directory, theme="cartoon")

            resolved = renderer.resolve_master(4, sides=6)
            generated = renderer.render(4, "#7A2EFF", resolved, sides=6)

            self.assertEqual(resolved.path, master)
            self.assertEqual(
                generated.path,
                dice
                / "d6"
                / "cache"
                / "v2"
                / "cartoon"
                / "7A2EFF"
                / "303030"
                / "101010"
                / "d6_4.gif",
            )

    def test_multiple_results_are_composed_and_cached_side_by_side(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dice = Path(directory) / "dice"
            d20_directory = dice / "d20"
            first_master = dice / "d6" / "themes" / "cartoon" / "d6_1.gif"
            second_master = dice / "d6" / "themes" / "cartoon" / "d6_2.gif"
            self.create_master(first_master)
            self.create_master(second_master)
            renderer = D20AnimationRenderer(d20_directory, theme="cartoon")
            masters = (
                renderer.resolve_master(1, sides=6),
                renderer.resolve_master(2, sides=6),
                renderer.resolve_master(1, sides=6),
            )

            generated = renderer.render_many(
                (1, 2, 1),
                "#7A2EFF",
                masters,
                edge_color="#FFD700",
                number_color="#101010",
                sides=6,
            )

            self.assertIsNotNone(generated)
            self.assertIn("groups", generated.path.parts)
            self.assertAlmostEqual(generated.duration_seconds, 0.5)
            with Image.open(generated.path) as animation:
                self.assertEqual(animation.size, (639, 213))
                self.assertEqual(animation.n_frames, 2)
                self.assertNotIn("loop", animation.info)
            with Image.open(generated.result_image_path) as result_image:
                self.assertEqual(result_image.size, (480, 160))

            modified_time = generated.path.stat().st_mtime_ns
            cached = renderer.render_many(
                (1, 2, 1),
                "#7A2EFF",
                masters,
                edge_color="#FFD700",
                number_color="#101010",
                sides=6,
            )
            self.assertEqual(cached.path, generated.path)
            self.assertEqual(cached.path.stat().st_mtime_ns, modified_time)

    def test_group_result_dice_are_equal_sized_and_keep_roll_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            first = output_directory / "first.png"
            second = output_directory / "second.png"
            output = output_directory / "group.png"
            Image.new("RGBA", (20, 20), (255, 0, 0, 255)).save(first)
            Image.new("RGBA", (10, 10), (0, 0, 255, 255)).save(second)

            D20AnimationRenderer._save_group_result_image(
                [first, second], output
            )

            with Image.open(output) as group:
                self.assertEqual(group.size, (320, 160))
                self.assertEqual(group.getpixel((80, 80))[:3], (255, 0, 0))
                self.assertEqual(group.getpixel((240, 80))[:3], (0, 0, 255))

    def test_group_result_glow_is_applied_only_to_selected_dice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_directory = Path(directory)
            first = output_directory / "first.png"
            second = output_directory / "second.png"
            output = output_directory / "group.png"
            Image.new("RGBA", (20, 20), (255, 255, 255, 255)).save(first)
            Image.new("RGBA", (20, 20), (255, 255, 255, 255)).save(second)

            D20AnimationRenderer._save_group_result_image(
                [first, second], output, (None, "#E74C3C")
            )

            with Image.open(output) as group:
                alpha = group.convert("RGBA").getchannel("A")
                plain_box = alpha.crop((0, 0, 160, 160)).getbbox()
                glowing_box = alpha.crop((160, 0, 320, 160)).getbbox()
                self.assertGreater(glowing_box[2] - glowing_box[0], plain_box[2] - plain_box[0])
                self.assertGreater(glowing_box[3] - glowing_box[1], plain_box[3] - plain_box[1])

    def test_glow_uses_the_requested_color_behind_the_die(self) -> None:
        die = Image.new("RGBA", (20, 20))
        die.paste((255, 255, 255, 255), (8, 8, 12, 12))

        smooth_glow = D20AnimationRenderer._glow_from_alpha(
            die.getchannel("A"), "#2ECC71", radius=3
        )

        outside = smooth_glow.getpixel((6, 10))
        far_outside = smooth_glow.getpixel((2, 10))
        self.assertGreater(outside[3], 0)
        self.assertGreater(outside[3], far_outside[3])
        self.assertGreater(outside[1], outside[0])
        self.assertGreater(outside[1], outside[2])

        gif_glow = D20AnimationRenderer._glow_image(die, "#2ECC71", radius=3)
        self.assertLessEqual(set(gif_glow.getchannel("A").getdata()), {0, 255})
        visible_colors = {
            pixel[:3] for pixel in gif_glow.getdata() if pixel[3] == 255
        }
        self.assertGreater(len(visible_colors), 2)

    def test_edge_mask_applies_a_separate_tint(self) -> None:
        source = Image.new("RGBA", (3, 1), (128, 128, 128, 255))
        edge_mask = Image.new("L", (3, 1), 0)
        edge_mask.putpixel((1, 0), 255)
        number_mask = Image.new("L", (3, 1), 0)
        number_mask.putpixel((2, 0), 255)

        tinted = D20AnimationRenderer._tint_frame(
            source,
            "#7A2EFF",
            "#FFD700",
            edge_mask,
            "#F5F5F5",
            number_mask,
        )

        self.assertEqual(tinted.getpixel((0, 0)), (86, 39, 170, 255))
        self.assertEqual(tinted.getpixel((1, 0)), (255, 215, 0, 255))
        self.assertEqual(tinted.getpixel((2, 0)), (245, 245, 245, 255))

    def test_edge_colors_have_distinct_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            master = assets / "themes" / "cartoon" / "d20_17.gif"
            self.create_master(master)
            self.create_master(master.with_name("d20_17_edges.gif"), dark=0, light=255)
            renderer = D20AnimationRenderer(assets, theme="cartoon")

            gold = renderer.render(17, "#7A2EFF", edge_color="#FFD700")
            black = renderer.render(17, "#7A2EFF", edge_color="#101010")

            self.assertNotEqual(gold.path, black.path)
            self.assertIn("FFD700", gold.path.parts)
            self.assertIn("101010", black.path.parts)

    def test_number_colors_have_distinct_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            master = assets / "themes" / "cartoon" / "d20_17.gif"
            self.create_master(master)
            self.create_master(
                master.with_name("d20_17_numbers.gif"), dark=0, light=255
            )
            renderer = D20AnimationRenderer(assets, theme="cartoon")

            white = renderer.render(17, "#7A2EFF", number_color="#F5F5F5")
            black = renderer.render(17, "#7A2EFF", number_color="#101010")

            self.assertNotEqual(white.path, black.path)
            self.assertIn("F5F5F5", white.path.parts)
            self.assertIn("101010", black.path.parts)

    def test_missing_selected_theme_falls_back_to_classic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            classic = assets / "themes" / "classic" / "d20_17.gif"
            self.create_master(classic)
            renderer = D20AnimationRenderer(assets, theme="cartoon")

            with self.assertLogs("rpg_bot.dice_visuals", level="WARNING"):
                resolved = renderer.resolve_master(17)

            self.assertEqual(resolved.path, classic)
            self.assertEqual(resolved.theme, "classic")

    def test_themes_with_same_result_never_share_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory) / "d20"
            self.create_master(assets / "themes" / "classic" / "d20_17.gif")
            self.create_master(
                assets / "themes" / "cartoon" / "d20_17.gif",
                dark=80,
                light=220,
            )

            classic = D20AnimationRenderer(assets, theme="classic").render(
                17, "#7A2EFF"
            )
            cartoon = D20AnimationRenderer(assets, theme="cartoon").render(
                17, "#7A2EFF"
            )

            self.assertNotEqual(classic.path, cartoon.path)
            self.assertIn("classic", classic.path.parts)
            self.assertIn("cartoon", cartoon.path.parts)

    def test_missing_master_falls_back_without_creating_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            renderer = D20AnimationRenderer(Path(directory) / "d20", theme="cartoon")

            with self.assertLogs("rpg_bot.dice_visuals", level="WARNING"):
                self.assertIsNone(renderer.render(17, "#7A2EFF"))
            self.assertFalse(renderer.cache_directory.exists())


if __name__ == "__main__":
    unittest.main()
