"""Canvas, fallback styling, fonts, and PNG output for dungeon maps."""

from io import BytesIO
from random import Random

from PIL import Image, ImageDraw, ImageFont

from .assets import MAP_HEIGHT, MAP_WIDTH, _loaded_map_background


def _map_canvas() -> Image.Image:
    """Return a fresh map canvas, falling back if the asset is unavailable."""
    background = _loaded_map_background()
    if background is not None:
        return background.copy()

    image = Image.new("RGB", (MAP_WIDTH, MAP_HEIGHT), "#15120f")
    _dark_fantasy_backdrop(ImageDraw.Draw(image))
    return image


def _dark_fantasy_backdrop(draw: ImageDraw.ImageDraw) -> None:
    """Paint a fallback stone-and-brass frame if the asset is unavailable."""
    for y in range(MAP_HEIGHT):
        shade = 20 + int(8 * y / MAP_HEIGHT)
        draw.line((0, y, MAP_WIDTH, y), fill=(shade, shade - 3, shade - 7))
    random = Random(7319)
    for _ in range(4200):
        x = random.randrange(MAP_WIDTH)
        y = random.randrange(MAP_HEIGHT)
        value = random.choice((24, 27, 30, 34, 38))
        draw.point((x, y), fill=(value, value - 4, value - 8))
    for _ in range(95):
        x = random.randrange(55, MAP_WIDTH - 55)
        y = random.randrange(55, MAP_HEIGHT - 55)
        length = random.randrange(12, 70)
        draw.line(
            (
                x,
                y,
                min(MAP_WIDTH - 55, x + length),
                y + random.choice((-2, -1, 1, 2)),
            ),
            fill=random.choice(("#211d18", "#2b251e", "#171411")),
            width=1,
        )

    for inset in range(18):
        shade = 12 + inset // 3
        draw.rectangle(
            (inset, inset, MAP_WIDTH - inset - 1, MAP_HEIGHT - inset - 1),
            outline=(shade, max(7, shade - 3), max(5, shade - 6)),
        )

    outer = (28, 20, MAP_WIDTH - 28, MAP_HEIGHT - 20)
    inner = (42, 34, MAP_WIDTH - 42, MAP_HEIGHT - 34)
    draw.rounded_rectangle(outer, radius=22, outline="#332a20", width=8)
    draw.rounded_rectangle(inner, radius=18, outline="#84683a", width=3)
    for x, y, sx, sy in (
        (50, 42, 1, 1),
        (MAP_WIDTH - 50, 42, -1, 1),
        (50, MAP_HEIGHT - 42, 1, -1),
        (MAP_WIDTH - 50, MAP_HEIGHT - 42, -1, -1),
    ):
        draw.line((x, y, x + sx * 34, y), fill="#b08b4b", width=4)
        draw.line((x, y, x, y + sy * 34), fill="#b08b4b", width=4)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#b08b4b")


def _font(
    size: int, *, heading: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ("georgiab.ttf", "DejaVuSerif-Bold.ttf", "timesbd.ttf")
        if heading
        else ("georgia.ttf", "DejaVuSerif.ttf", "arial.ttf")
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _png(image: Image.Image) -> BytesIO:
    output = BytesIO()
    image.save(output, "PNG", optimize=True)
    output.seek(0)
    return output
