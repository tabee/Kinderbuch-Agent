"""``--pages`` grammar tests (spec §8.2, §13)."""

from __future__ import annotations

import pytest

from kb.core.pagespec import parse_page_spec


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("1", {1}),
        ("3,5", {3, 5}),
        ("7-9", {7, 8, 9}),
        ("3,5,7-9", {3, 5, 7, 8, 9}),
        ("2-2", {2}),
        (" 1 , 4-5 ", {1, 4, 5}),
        ("3,3,3", {3}),
    ],
)
def test_valid_specs(spec: str, expected: set[int]) -> None:
    assert parse_page_spec(spec) == expected


@pytest.mark.parametrize(
    "spec",
    ["", ",", "0", "-1", "a", "1,", "5-3", "1-", "-", "1-2-3", "1.5", "1 2"],
)
def test_invalid_specs_raise(spec: str) -> None:
    with pytest.raises(ValueError, match="invalid page spec"):
        parse_page_spec(spec)
