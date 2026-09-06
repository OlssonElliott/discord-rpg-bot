"""Render Rollkeeper's neutral polyhedral dice with Blender, then encode GIFs.

Run this file with the project's normal Python interpreter. It starts Blender in
background mode for the 3D render; Blender is never needed by the Discord bot.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageChops


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dice_assets import (  # noqa: E402
    DEFAULT_DICE_THEME,
    DiceAssetLayout,
    InvalidDiceThemeError,
    normalize_dice_theme,
)


BLENDER_RENDER_SCRIPT = Path(__file__).with_name("render_d20_blender.py")
FINAL_HOLD_SECONDS = 0.9
SUPPORTED_DICE_SIDES = (4, 6, 8, 10, 12, 20)


def parse_results(value: str | list[str], sides: int = 20) -> list[int]:
    """Parse space/comma-separated values and ranges such as ``1 5 10-12``."""
    results: set[int] = set()
    values = [value] if isinstance(value, str) else value
    try:
        for value_part in values:
            for part in value_part.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    start_text, end_text = part.split("-", 1)
                    start, end = int(start_text), int(end_text)
                    if start > end:
                        raise ValueError
                    results.update(range(start, end + 1))
                else:
                    results.add(int(part))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Results must look like `1-{sides}`, `3`, or `1,3,{sides}`."
        ) from error

    if not results or min(results) < 1 or max(results) > sides:
        raise argparse.ArgumentTypeError(
            f"D{sides} results must be between 1 and {sides}."
        )
    return sorted(results)


def parse_theme(value: str) -> str:
    try:
        return normalize_dice_theme(value)
    except InvalidDiceThemeError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def output_directory_for_theme(
    theme: str,
    explicit_directory: Path | None = None,
    dice_directory: Path | None = None,
    sides: int = 20,
) -> Path:
    if explicit_directory is not None:
        return explicit_directory.resolve()
    layout = DiceAssetLayout(dice_directory or PROJECT_ROOT / "assets" / "dice")
    return layout.theme_directory(sides, theme).resolve()


def migrate_legacy_masters(layout: DiceAssetLayout) -> list[Path]:
    """Copy legacy masters into classic without deleting or replacing anything."""
    copied: list[Path] = []
    for result in range(1, 21):
        legacy_master = layout.legacy_master_path(20, result)
        themed_master = layout.master_path(20, DEFAULT_DICE_THEME, result)
        for suffix in ("", "_edges", "_numbers"):
            source = legacy_master.with_name(f"{legacy_master.stem}{suffix}.gif")
            destination = themed_master.with_name(
                f"{themed_master.stem}{suffix}.gif"
            )
            if source.is_file() and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied.append(destination)
    return copied


def ensure_outputs_available(
    output_directory: Path,
    results: list[int],
    overwrite: bool,
    sides: int = 20,
) -> None:
    if overwrite:
        return
    existing = [
        path
        for result in results
        for path in (
            output_directory / f"d{sides}_{result}.gif",
            output_directory / f"d{sides}_{result}_edges.gif",
            output_directory / f"d{sides}_{result}_numbers.gif",
        )
        if path.exists()
    ]
    if existing:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(
            f"Refusing to overwrite existing theme assets: {names}. "
            "Pass --overwrite to replace them intentionally."
        )


def find_blender(explicit_path: str | None) -> Path:
    """Locate Blender from an argument, PATH, or common desktop locations."""
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(f"Blender was not found at: {candidate}")

    from_path = shutil.which("blender")
    if from_path:
        return Path(from_path).resolve()

    candidates: list[Path] = []
    if sys.platform == "win32":
        program_files = os.environ.get("ProgramFiles")
        if program_files:
            candidates.extend(
                Path(program_files).glob(
                    "Blender Foundation/Blender */blender.exe"
                )
            )
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Blender.app/Contents/MacOS/Blender"))
    else:
        candidates.extend((Path("/usr/bin/blender"), Path("/snap/bin/blender")))

    installed = sorted((path for path in candidates if path.is_file()), reverse=True)
    if installed:
        return installed[0].resolve()
    raise FileNotFoundError(
        "Blender was not found. Install Blender 4.2 or newer, add it to PATH, "
        "or pass --blender with the full executable path."
    )


def build_global_palette(frames: list[Image.Image], colors: int) -> Image.Image:
    """Build one compact palette for every frame to avoid color flicker."""
    samples: list[Image.Image] = []
    for frame in frames:
        sample = frame.convert("RGB")
        sample.thumbnail((96, 96), Image.Resampling.LANCZOS)
        samples.append(sample)

    width = max(sample.width for sample in samples)
    height = sum(sample.height for sample in samples)
    sheet = Image.new("RGB", (width, height))
    offset = 0
    for sample in samples:
        sheet.paste(sample, (0, offset))
        offset += sample.height
    return sheet.quantize(
        colors=colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )


def convert_frames_to_gif(
    frame_directory: Path,
    output_path: Path,
    fps: int,
    colors: int,
    overwrite: bool = False,
    final_hold_ms: int | None = None,
) -> tuple[int, float]:
    """Convert one transparent PNG sequence into an atomic, optimized GIF."""
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite {output_path}; pass --overwrite to replace it."
        )
    frame_paths = sorted(frame_directory.glob("frame_*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"No rendered PNG frames found in {frame_directory}")

    frames: list[Image.Image] = []
    for path in frame_paths:
        with Image.open(path) as source:
            frames.append(source.convert("RGBA"))

    palette = build_global_palette(frames, colors)
    gif_frames: list[Image.Image] = []
    for frame in frames:
        quantized = frame.convert("RGB").quantize(
            palette=palette,
            dither=Image.Dither.NONE,
        )
        alpha = frame.getchannel("A")
        opaque_pixels = alpha.point(lambda value: 255 if value >= 128 else 0)
        reserved_index_pixels = quantized.point(
            lambda index: 255 if index == 255 else 0
        )
        opaque_reserved_pixels = ImageChops.multiply(
            opaque_pixels, reserved_index_pixels
        )
        quantized.paste(colors - 1, mask=opaque_reserved_pixels)
        transparent_pixels = alpha.point(
            lambda alpha: 255 if alpha < 128 else 0
        )
        quantized.paste(255, mask=transparent_pixels)
        quantized.info["transparency"] = 255
        quantized.info["disposal"] = 2
        gif_frames.append(quantized)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".tmp.gif")
    frame_duration_ms = round(1000 / fps)
    frame_durations = [frame_duration_ms] * len(gif_frames)
    if final_hold_ms is not None:
        frame_durations[-1] = final_hold_ms
    try:
        gif_frames[0].save(
            temporary_path,
            format="GIF",
            save_all=True,
            append_images=gif_frames[1:],
            duration=frame_durations,
            disposal=2,
            transparency=255,
            optimize=True,
        )
        if output_path.exists() and not overwrite:
            raise FileExistsError(
                f"Refusing to overwrite {output_path}; pass --overwrite to replace it."
            )
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return output_path.stat().st_size, sum(frame_durations) / 1000


def prepare_tintable_frames(
    source_directory: Path,
    output_directory: Path,
    normalize_to_final_bounds: bool = True,
) -> tuple[Path, Path, Path]:
    """Turn Blender's marker colors into neutral frames and tint masks."""
    source_paths = sorted(source_directory.glob("frame_*.png"))
    if not source_paths:
        raise FileNotFoundError(f"No rendered PNG frames found in {source_directory}")

    master_directory = output_directory / "master"
    edge_directory = output_directory / "edges"
    number_directory = output_directory / "numbers"
    master_directory.mkdir(parents=True, exist_ok=True)
    edge_directory.mkdir(parents=True, exist_ok=True)
    number_directory.mkdir(parents=True, exist_ok=True)
    for directory in (master_directory, edge_directory, number_directory):
        for old_frame in directory.glob("frame_*.png"):
            old_frame.unlink()

    with Image.open(source_paths[-1]) as final_image:
        final_alpha = final_image.convert("RGBA").getchannel("A").point(
            lambda value: 255 if value >= 128 else 0
        )
    target_box = final_alpha.getbbox()
    if target_box is None:
        raise ValueError(f"Final rendered frame is transparent: {source_paths[-1]}")
    target_width = target_box[2] - target_box[0]
    target_height = target_box[3] - target_box[1]

    for frame_number, source_path in enumerate(source_paths, start=1):
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")
        source_alpha = source.getchannel("A").point(
            lambda value: 255 if value >= 128 else 0
        )
        source_box = source_alpha.getbbox()
        if source_box is None:
            raise ValueError(f"Rendered frame is transparent: {source_path}")
        if normalize_to_final_bounds:
            rendered_die = source.crop(source_box)
            rendered_alpha = source_alpha.crop(source_box)
            if rendered_die.size != (target_width, target_height):
                rendered_die = rendered_die.resize(
                    (target_width, target_height), Image.Resampling.LANCZOS
                )
                rendered_alpha = rendered_alpha.resize(
                    (target_width, target_height), Image.Resampling.NEAREST
                )
            rendered_die.putalpha(rendered_alpha)
            source = Image.new("RGBA", source.size)
            source.alpha_composite(rendered_die, (target_box[0], target_box[1]))
        else:
            # A tetrahedron's projected silhouette naturally changes width while
            # turning. Stretching every frame to the final triangular bounds
            # deforms its angles and makes the d4 look skewed during the spin.
            source.putalpha(source_alpha)

        red, green, blue, alpha = source.split()
        other_channels = ImageChops.lighter(red, blue)
        green_dominance = ImageChops.subtract(green, other_channels)
        edge_presence = green_dominance.point(
            lambda value: 255 if value > 1 else 0
        )
        other_number_channels = ImageChops.lighter(red, green)
        blue_dominance = ImageChops.subtract(blue, other_number_channels)
        number_presence = blue_dominance.point(
            lambda value: 255 if value > 1 else 0
        )

        edge_luminance = green.point(lambda value: round(value * 0.42))
        neutral_edge = Image.merge(
            "RGBA", (edge_luminance, edge_luminance, edge_luminance, alpha)
        )
        neutral_master = Image.composite(neutral_edge, source, edge_presence)
        neutral_number_channel = Image.new("L", source.size, 128)
        neutral_number = Image.merge(
            "RGBA",
            (
                neutral_number_channel,
                neutral_number_channel,
                neutral_number_channel,
                alpha,
            ),
        )
        neutral_master = Image.composite(
            neutral_number, neutral_master, number_presence
        )
        edge_mask_rgba = Image.merge(
            "RGBA", (edge_presence, edge_presence, edge_presence, alpha)
        )
        number_mask_rgba = Image.merge(
            "RGBA", (number_presence, number_presence, number_presence, alpha)
        )

        frame_name = f"frame_{frame_number:04d}.png"
        neutral_master.save(master_directory / frame_name)
        edge_mask_rgba.save(edge_directory / frame_name)
        number_mask_rgba.save(number_directory / frame_name)

    return master_directory, edge_directory, number_directory


def render_with_blender(
    blender_path: Path,
    frames_directory: Path,
    results: list[int],
    resolution: int,
    fps: int,
    duration: float,
    samples: int,
    sides: int = 20,
) -> None:
    command = [
        str(blender_path),
        "--background",
        "--factory-startup",
        "--python",
        str(BLENDER_RENDER_SCRIPT),
        "--",
        "--output-dir",
        str(frames_directory),
        "--sides",
        str(sides),
        "--results",
        ",".join(str(result) for result in results),
        "--resolution",
        str(resolution),
        "--fps",
        str(fps),
        "--duration",
        str(duration),
        "--samples",
        str(samples),
    ]
    print(f"Rendering {len(results)} result(s) with {blender_path}...")
    subprocess.run(command, check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Rollkeeper's neutral polyhedral dice GIFs offline."
    )
    parser.add_argument(
        "--theme",
        type=parse_theme,
        default=DEFAULT_DICE_THEME,
        help=f"Theme name to generate (default: {DEFAULT_DICE_THEME}).",
    )
    parser.add_argument(
        "--sides",
        type=int,
        nargs="+",
        choices=SUPPORTED_DICE_SIDES,
        default=[20],
        help="Dice types to generate; defaults to 20.",
    )
    parser.add_argument(
        "--blender",
        help="Full path to blender.exe if Blender is not available on PATH.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Override the output directory when generating one dice type.",
    )
    parser.add_argument(
        "--results",
        nargs="+",
        metavar="RESULT",
        help="Results to render for one dice type. Defaults to every face.",
    )
    parser.add_argument("--resolution", type=int, default=384)
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument("--duration", type=float, default=2.3)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument(
        "--colors",
        type=int,
        default=128,
        help="GIF palette colors; 128 is a good size/quality balance.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Intentionally replace existing GIFs in the selected theme.",
    )
    parser.add_argument(
        "--keep-frames",
        type=Path,
        help="Keep intermediate PNG sequences in this directory for inspection.",
    )
    return parser


def validate_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    args.sides = sorted(set(args.sides))
    if args.output_dir is not None and len(args.sides) != 1:
        parser.error("--output-dir can only be used with one --sides value.")
    if args.results is not None and len(args.sides) != 1:
        parser.error("--results can only be used with one --sides value.")
    try:
        args.results = (
            parse_results(args.results, args.sides[0])
            if args.results is not None
            else (
                list(range(1, args.sides[0] + 1))
                if len(args.sides) == 1
                else None
            )
        )
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    if not 128 <= args.resolution <= 512:
        parser.error("--resolution must be between 128 and 512.")
    if not 10 <= args.fps <= 30:
        parser.error("--fps must be between 10 and 30.")
    if not 1.0 <= args.duration <= 4.0:
        parser.error("--duration must be between 1.0 and 4.0 seconds.")
    if not 8 <= args.samples <= 128:
        parser.error("--samples must be between 8 and 128.")
    if not 32 <= args.colors <= 255:
        parser.error("--colors must be between 32 and 255.")


def generate(args: argparse.Namespace) -> None:
    layout = DiceAssetLayout(PROJECT_ROOT / "assets" / "dice")
    migrated = migrate_legacy_masters(layout)
    for path in migrated:
        print(f"Preserved legacy master as {path}")

    results_by_sides = {
        sides: args.results or list(range(1, sides + 1)) for sides in args.sides
    }
    output_directories = {
        sides: output_directory_for_theme(
            args.theme,
            args.output_dir if len(args.sides) == 1 else None,
            sides=sides,
        )
        for sides in args.sides
    }
    for sides in args.sides:
        ensure_outputs_available(
            output_directories[sides],
            results_by_sides[sides],
            args.overwrite,
            sides,
        )
        output_directories[sides].mkdir(parents=True, exist_ok=True)
    blender_path = find_blender(args.blender)
    started = time.perf_counter()

    if args.keep_frames:
        frames_directory = args.keep_frames.resolve()
        frames_directory.mkdir(parents=True, exist_ok=True)
        temporary_context = None
    else:
        temporary_context = tempfile.TemporaryDirectory(prefix="rollkeeper-dice-")
        frames_directory = Path(temporary_context.name)

    try:
        total_size = 0
        total_results = 0
        for sides in args.sides:
            side_frames_directory = frames_directory / f"d{sides}"
            render_with_blender(
                blender_path,
                side_frames_directory,
                results_by_sides[sides],
                args.resolution,
                args.fps,
                args.duration,
                args.samples,
                sides,
            )
            output_directory = output_directories[sides]
            for result in results_by_sides[sides]:
                prepared_directory = (
                    frames_directory / "tintable" / f"d{sides}_{result}"
                )
                master_frames, edge_frames, number_frames = prepare_tintable_frames(
                    side_frames_directory / f"d{sides}_{result}",
                    prepared_directory,
                    normalize_to_final_bounds=sides != 4,
                )
                output_path = output_directory / f"d{sides}_{result}.gif"
                size, actual_duration = convert_frames_to_gif(
                    master_frames,
                    output_path,
                    args.fps,
                    args.colors,
                    overwrite=args.overwrite,
                    final_hold_ms=round(FINAL_HOLD_SECONDS * 1000),
                )
                edge_output_path = output_directory / f"d{sides}_{result}_edges.gif"
                edge_size, edge_duration = convert_frames_to_gif(
                    edge_frames,
                    edge_output_path,
                    args.fps,
                    min(args.colors, 64),
                    overwrite=args.overwrite,
                    final_hold_ms=round(FINAL_HOLD_SECONDS * 1000),
                )
                number_output_path = output_directory / f"d{sides}_{result}_numbers.gif"
                number_size, number_duration = convert_frames_to_gif(
                    number_frames,
                    number_output_path,
                    args.fps,
                    min(args.colors, 64),
                    overwrite=args.overwrite,
                    final_hold_ms=round(FINAL_HOLD_SECONDS * 1000),
                )
                if len({actual_duration, edge_duration, number_duration}) != 1:
                    raise RuntimeError("Master and mask GIF durations do not match.")
                total_size += size + edge_size + number_size
                total_results += 1
                print(
                    f"Created {output_path.name} + edge/number masks: "
                    f"{(size + edge_size + number_size) / (1024 * 1024):.2f} MiB, "
                    f"{actual_duration:.2f}s"
                )
    finally:
        if temporary_context is not None:
            temporary_context.cleanup()

    elapsed = time.perf_counter() - started
    print(
        f"Finished {total_results} result animation(s) in {elapsed / 60:.1f} minutes "
        f"({total_size / (1024 * 1024):.1f} MiB total)."
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_arguments(parser, args)
    try:
        generate(args)
    except (FileExistsError, FileNotFoundError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Asset generation failed: {error}\n")


if __name__ == "__main__":
    main()
