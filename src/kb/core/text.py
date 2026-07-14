"""Hygiene for interactively typed text and argv values."""

from __future__ import annotations


def clean_text(value: str) -> str:
    """Repair mojibake from mis-decoded terminal input or argv.

    Terminals without the IUTF8 flag (e.g. ``docker compose exec`` TTYs) split
    multi-byte UTF-8 characters when the user edits a line: backspacing over an
    umlaut removes one byte, leaving a lone continuation byte in the stream.
    Python's surrogateescape decoding turns such bytes into lone surrogates
    (U+DC80-U+DCFF), which crash every strict UTF-8 encoder downstream — the
    Anthropic/Gemini JSON serializers and YAML state writes alike.

    Round-tripping restores sequences that were merely mis-decoded (umlauts
    come back intact) and replaces irreparable stray bytes with U+FFFD.
    """
    try:
        value.encode("utf-8")
        return value
    except UnicodeEncodeError:
        return value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
