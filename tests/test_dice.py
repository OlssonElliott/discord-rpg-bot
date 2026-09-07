import unittest
from unittest.mock import patch

from rpg_bot.dice import DiceExpressionError, parse, roll


class DiceTests(unittest.TestCase):
    def test_supported_expressions_are_canonicalized(self) -> None:
        self.assertEqual(parse("d20"), (1, 20, 0, "1d20"))
        self.assertEqual(parse("1d20+4"), (1, 20, 4, "1d20+4"))
        self.assertEqual(parse("2D6-3"), (2, 6, -3, "2d6-3"))

    def test_roll_calculates_results_and_modifier(self) -> None:
        with patch("rpg_bot.dice.secrets.randbelow", side_effect=[15, 2]):
            result = roll("2d20+4")
        self.assertEqual(result.results, (16, 3))
        self.assertEqual(result.total, 23)

    def test_advantage_and_disadvantage_keep_the_correct_d20(self) -> None:
        with patch("rpg_bot.dice.secrets.randbelow", side_effect=[5, 16]):
            advantage = roll("1d20+4", mode="advantage")
        self.assertEqual(advantage.results, (6, 17))
        self.assertEqual(advantage.kept_result, 17)
        self.assertEqual(advantage.total, 21)

        with patch("rpg_bot.dice.secrets.randbelow", side_effect=[5, 16]):
            disadvantage = roll("1d20+4", mode="disadvantage")
        self.assertEqual(disadvantage.results, (6, 17))
        self.assertEqual(disadvantage.kept_result, 6)
        self.assertEqual(disadvantage.total, 10)

    def test_advantage_requires_one_d20(self) -> None:
        for expression in ("2d20", "1d12", "3d6"):
            with self.subTest(expression=expression):
                with self.assertRaises(DiceExpressionError):
                    roll(expression, mode="advantage")

    def test_unknown_roll_mode_is_rejected(self) -> None:
        with self.assertRaises(DiceExpressionError):
            roll("1d20", mode="lucky")

    def test_malformed_or_unsafe_expressions_are_rejected(self) -> None:
        for expression in (
            "20",
            "d",
            "2d6++3",
            "0d20",
            "101d6",
            "1d1",
            "9" * 1_000 + "d20",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(DiceExpressionError):
                    parse(expression)


if __name__ == "__main__":
    unittest.main()
