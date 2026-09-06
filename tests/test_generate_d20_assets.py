import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scripts.generate_d20_assets import (
    convert_frames_to_gif,
    parse_results,
    prepare_tintable_frames,
)
from dice_assets import DiceAssetLayout
from scripts.generate_d20_assets import (
    build_parser,
    ensure_outputs_available,
    migrate_legacy_masters,
    output_directory_for_theme,
    validate_arguments,
)


class GenerateD20AssetsTests(unittest.TestCase):
    def test_result_selection_accepts_ranges_and_lists(self) -> None:
        self.assertEqual(parse_results("1-3,17,20"), [1, 2, 3, 17, 20])
        self.assertEqual(parse_results(["1", "10", "20"]), [1, 10, 20])
        self.assertEqual(parse_results("1-6", sides=6), [1, 2, 3, 4, 5, 6])

    def test_omitting_results_selects_all_twenty(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--theme", "classic"])
        validate_arguments(parser, args)

        self.assertEqual(args.results, list(range(1, 21)))

    def test_theme_selects_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = output_directory_for_theme(
                "cartoon", dice_directory=Path(directory) / "dice"
            )
            self.assertEqual(
                output,
                Path(directory).resolve()
                / "dice"
                / "d20"
                / "themes"
                / "cartoon",
            )

            d6_output = output_directory_for_theme(
                "cartoon", dice_directory=Path(directory) / "dice", sides=6
            )
            self.assertEqual(
                d6_output,
                Path(directory).resolve()
                / "dice"
                / "d6"
                / "themes"
                / "cartoon",
            )

    def test_multiple_dice_types_select_all_faces(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--theme", "cartoon", "--sides", "4", "6"])
        validate_arguments(parser, args)

        self.assertEqual(args.sides, [4, 6])
        self.assertIsNone(args.results)

    def test_existing_output_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "d20_10.gif").write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                ensure_outputs_available(output, [1, 10, 20], overwrite=False)
            ensure_outputs_available(output, [1, 10, 20], overwrite=True)

    def test_existing_edge_mask_also_requires_explicit_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "d20_10_edges.gif").write_bytes(b"existing")

            with self.assertRaises(FileExistsError):
                ensure_outputs_available(output, [10], overwrite=False)

            (output / "d20_10_edges.gif").unlink()
            (output / "d20_10_numbers.gif").write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                ensure_outputs_available(output, [10], overwrite=False)

    def test_legacy_migration_copies_without_replacing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layout = DiceAssetLayout(Path(directory) / "dice")
            legacy = layout.legacy_master_path(20, 1)
            classic = layout.master_path(20, "classic", 1)
            legacy_missing_classic = layout.legacy_master_path(20, 2)
            migrated_classic = layout.master_path(20, "classic", 2)
            legacy.parent.mkdir(parents=True)
            classic.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")
            classic.write_bytes(b"existing classic")
            legacy_missing_classic.write_bytes(b"legacy two")

            self.assertEqual(migrate_legacy_masters(layout), [migrated_classic])
            self.assertEqual(legacy.read_bytes(), b"legacy")
            self.assertEqual(classic.read_bytes(), b"existing classic")
            self.assertEqual(migrated_classic.read_bytes(), b"legacy two")

    def test_png_frames_are_converted_to_a_transparent_animated_gif(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            first = Image.new("RGBA", (16, 16), (90, 90, 90, 255))
            first.putpixel((0, 0), (0, 0, 0, 0))
            second = Image.new("RGBA", (16, 16), (180, 180, 180, 255))
            second.putpixel((0, 0), (0, 0, 0, 0))
            first.save(frames / "frame_0001.png")
            second.save(frames / "frame_0002.png")
            output = root / "d20_17.gif"

            size, duration = convert_frames_to_gif(frames, output, fps=20, colors=64)

            self.assertGreater(size, 0)
            self.assertAlmostEqual(duration, 0.1)
            with Image.open(output) as generated:
                self.assertEqual(generated.n_frames, 2)
                self.assertEqual(generated.info["duration"], 50)
                self.assertNotIn("loop", generated.info)
                self.assertEqual(generated.convert("RGBA").getpixel((0, 0))[3], 0)

            with self.assertRaises(FileExistsError):
                convert_frames_to_gif(frames, output, fps=20, colors=64)
            size, duration = convert_frames_to_gif(
                frames,
                output,
                fps=20,
                colors=64,
                overwrite=True,
                final_hold_ms=900,
            )
            self.assertGreater(size, 0)
            self.assertAlmostEqual(duration, 0.95)
            with Image.open(output) as generated:
                frame_durations = []
                for frame_number in range(generated.n_frames):
                    generated.seek(frame_number)
                    frame_durations.append(generated.info["duration"])
                self.assertEqual(frame_durations, [50, 900])
                self.assertNotIn("loop", generated.info)

    def test_green_edge_marker_becomes_neutral_master_and_mask(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            frame = Image.new("RGBA", (3, 1), (120, 120, 120, 255))
            frame.putpixel((1, 0), (4, 180, 4, 255))
            frame.putpixel((2, 0), (4, 4, 180, 255))
            frame.save(source / "frame_0001.png")

            masters, edges, numbers = prepare_tintable_frames(
                source, root / "prepared"
            )

            with Image.open(masters / "frame_0001.png") as master:
                face_pixel, edge_pixel, number_pixel = list(
                    master.convert("RGBA").getdata()
                )
            with Image.open(edges / "frame_0001.png") as mask:
                mask_pixels = list(mask.convert("RGBA").getdata())
            with Image.open(numbers / "frame_0001.png") as mask:
                number_mask_pixels = list(mask.convert("RGBA").getdata())
            self.assertEqual(face_pixel[:3], (120, 120, 120))
            self.assertEqual(edge_pixel[0], edge_pixel[1])
            self.assertEqual(edge_pixel[1], edge_pixel[2])
            self.assertEqual(number_pixel[:3], (128, 128, 128))
            self.assertEqual(mask_pixels[0][0], 0)
            self.assertGreater(mask_pixels[1][0], 240)
            self.assertEqual(number_mask_pixels[0][0], 0)
            self.assertGreater(number_mask_pixels[2][0], 240)

    def test_complete_blender_frames_are_normalized_to_final_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            narrow = Image.new("RGBA", (8, 6))
            narrow.paste((120, 120, 120, 255), (3, 2, 5, 4))
            wide = Image.new("RGBA", (8, 6))
            wide.paste((120, 120, 120, 255), (2, 2, 6, 4))
            narrow.save(source / "frame_0001.png")
            wide.save(source / "frame_0002.png")

            masters, _, _ = prepare_tintable_frames(source, root / "prepared")
            boxes = []
            alpha_frames = []
            for frame_path in sorted(masters.glob("frame_*.png")):
                with Image.open(frame_path) as frame:
                    alpha = frame.convert("RGBA").getchannel("A")
                    boxes.append(alpha.getbbox())
                    alpha_frames.append(alpha.tobytes())

            self.assertEqual(boxes, [(2, 2, 6, 4), (2, 2, 6, 4)])

    def test_d4_frames_can_preserve_their_projected_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            narrow = Image.new("RGBA", (8, 6))
            narrow.paste((120, 120, 120, 255), (3, 2, 5, 4))
            wide = Image.new("RGBA", (8, 6))
            wide.paste((120, 120, 120, 255), (2, 2, 6, 4))
            narrow.save(source / "frame_0001.png")
            wide.save(source / "frame_0002.png")

            masters, _, _ = prepare_tintable_frames(
                source,
                root / "prepared",
                normalize_to_final_bounds=False,
            )
            boxes = []
            for frame_path in sorted(masters.glob("frame_*.png")):
                with Image.open(frame_path) as frame:
                    boxes.append(frame.convert("RGBA").getchannel("A").getbbox())

            self.assertEqual(boxes, [(3, 2, 5, 4), (2, 2, 6, 4)])


if __name__ == "__main__":
    unittest.main()
