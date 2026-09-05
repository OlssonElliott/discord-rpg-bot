import unittest
from unittest.mock import patch

from dice import DiceExpressionError, parse, roll


class DiceTests(unittest.TestCase):
    def test_supported_expressions_are_canonicalized(self) -> None:
        self.assertEqual(parse("d20"), (1, 20, 0, "1d20"))
        self.assertEqual(parse("1d20+4"), (1, 20, 4, "1d20+4"))
        self.assertEqual(parse("2D6-3"), (2, 6, -3, "2d6-3"))

    def test_roll_calculates_results_and_modifier(self) -> None:
        with patch("dice.secrets.randbelow", side_effect=[15, 2]):
            result = roll("2d20+4")
        self.assertEqual(result.results, (16, 3))
        self.assertEqual(result.total, 23)

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
