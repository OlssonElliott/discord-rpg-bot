"""Shared request parsing helpers for the local DM dashboard API."""

from __future__ import annotations

from typing import Any


JsonObject = dict[str, Any]


def parse_text(body: JsonObject, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required.")
    return value.strip()


def parse_optional_text(
    body: JsonObject,
    field: str,
) -> str | None:
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be text.")
    return value.strip() or None


def parse_number(body: JsonObject, field: str) -> float:
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{field}' must be a number.")
    return float(value)


def parse_integer(
    body: JsonObject,
    field: str,
    *,
    default: int,
) -> int:
    value = body.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"'{field}' must be an integer.")
    return value


def parse_boolean(
    body: JsonObject,
    field: str,
    *,
    default: bool,
) -> bool:
    value = body.get(field, default)
    if not isinstance(value, bool):
        raise ValueError(f"'{field}' must be true or false.")
    return value
