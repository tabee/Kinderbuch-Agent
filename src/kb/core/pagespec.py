"""Parser for the ``--pages`` selection grammar (spec §8.2)."""

from __future__ import annotations


def parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like ``"3,5,7-9"`` into ``{3, 5, 7, 8, 9}``.

    Grammar: comma-separated positive integers and inclusive ranges ``a-b``
    with ``a <= b``. Anything else raises ``ValueError`` (usage error, §8.3).
    """
    pages: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        try:
            if not part:
                raise ValueError
            first, sep, second = part.partition("-")
            if sep:
                start, end = int(first), int(second)
                if start < 1 or end < start:
                    raise ValueError
                pages.update(range(start, end + 1))
            else:
                number = int(first)
                if number < 1:
                    raise ValueError
                pages.add(number)
        except ValueError:
            raise ValueError(
                f"invalid page spec {spec!r}: expected comma-separated positive "
                "integers and inclusive ranges, e.g. '3,5,7-9'"
            ) from None
    return pages
