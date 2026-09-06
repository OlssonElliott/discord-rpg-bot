"""Parsing and rolling for the deliberately small supported dice notation."""

from dataclasses import dataclass
import re
import secrets


_DICE_EXPRESSION = re.compile(
    r"(?P<count>\d*)d(?P<sides>\d+)(?P<modifier>[+-]\d+)?",
    re.IGNORECASE,
)

MAX_DICE = 100
MAX_SIDES = 10_000
MAX_MODIFIER = 1_000_000
ROLL_MODES = frozenset(("normal", "advantage", "disadvantage"))


class DiceExpressionError(ValueError):
    """Raised when an expression is unsupported or outside safe limits."""


@dataclass(frozen=True, slots=True)
class DiceRoll:
    expression: str
    count: int
    sides: int
    modifier: int
    results: tuple[int, ...]
    kept_result: int | None = None

    @property
    def total(self) -> int:
        rolled_total = (
            self.kept_result
            if self.kept_result is not None
            else sum(self.results)
        )
        return rolled_total + self.modifier


def parse(expression: str) -> tuple[int, int, int, str]:
    cleaned = expression.strip().lower()
    match = _DICE_EXPRESSION.fullmatch(cleaned)
    if match is None:
        raise DiceExpressionError(
            "Use dice notation such as `d20`, `1d20+4`, or `2d6-1`."
        )

    count_text = match.group("count") or "1"
    sides_text = match.group("sides")
    modifier_text = match.group("modifier") or "0"
    if (
        len(count_text) > 3
        or len(sides_text) > 5
        or len(modifier_text.lstrip("+-")) > 7
    ):
        raise DiceExpressionError("That dice expression is too large.")

    count = int(count_text)
    sides = int(sides_text)
    modifier = int(modifier_text)

    if not 1 <= count <= MAX_DICE:
        raise DiceExpressionError(f"The number of dice must be between 1 and {MAX_DICE}.")
    if not 2 <= sides <= MAX_SIDES:
        raise DiceExpressionError(f"Dice must have between 2 and {MAX_SIDES:,} sides.")
    if abs(modifier) > MAX_MODIFIER:
        raise DiceExpressionError(
            f"The modifier must be between -{MAX_MODIFIER:,} and +{MAX_MODIFIER:,}."
        )

    canonical = f"{count}d{sides}"
    if modifier:
        canonical += f"{modifier:+d}"
    return count, sides, modifier, canonical


def roll(expression: str, mode: str = "normal") -> DiceRoll:
    count, sides, modifier, canonical = parse(expression)
    normalized_mode = mode.strip().lower()
    if normalized_mode not in ROLL_MODES:
        raise DiceExpressionError(
            "Roll mode must be normal, advantage, or disadvantage."
        )
    if normalized_mode != "normal" and (count != 1 or sides != 20):
        raise DiceExpressionError(
            "Advantage and disadvantage currently require a single d20 expression, "
            "such as `1d20+4`."
        )

    actual_count = 2 if normalized_mode != "normal" else count
    results = tuple(secrets.randbelow(sides) + 1 for _ in range(actual_count))
    kept_result = None
    if normalized_mode == "advantage":
        kept_result = max(results)
    elif normalized_mode == "disadvantage":
        kept_result = min(results)
    return DiceRoll(canonical, actual_count, sides, modifier, results, kept_result)
