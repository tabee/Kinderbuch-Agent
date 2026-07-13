"""Deterministic offline LLM provider for development, tests, and phase gates (§15).

Synthesizes schema-valid Pydantic instances by introspecting the target model:
no network, no credentials, zero cost. Output is themed (Swiss-Thai myths) and
varies deterministically with the request prompt, so different pages get
different text and different image prompts — while identical requests always
produce identical results (idempotency, HC-4.1). ``dict[str, str]`` fields are
filled for every configured language, including real Thai text so the PDF gate
exercises libthai line breaking (HC-3.4).
"""

from __future__ import annotations

import hashlib
import re
import types
import typing
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from kb.errors import KBError
from kb.llm.base import LLMProvider, T

# Themed bilingual sample bank (Swiss alpine folklore meets Thai mythology).
_TEXTS: list[dict[str, str]] = [
    {
        "en": "High in the snowy Alps, Heidi the marmot heard a song from far-away Siam.",
        "th": "บนเทือกเขาแอลป์ที่ปกคลุมด้วยหิมะ ไฮดี้มาร์มอตได้ยินเสียงเพลงจากแดนสยามอันไกลโพ้น",
    },
    {
        "en": "Nari the little naga glided up the mountain stream, curious about the snow.",
        "th": "นารีนาคน้อยเลื้อยทวนลำธารภูเขาขึ้นมา ด้วยความสงสัยในหิมะ",
    },
    {
        "en": "Together they shared warm bread and mango sticky rice under the old pine.",
        "th": "ทั้งสองแบ่งปันขนมปังอุ่นและข้าวเหนียวมะม่วงใต้ต้นสนเก่าแก่",
    },
    {
        "en": "The mountain spirit smiled and rang the great cowbell across the valley.",
        "th": "ภูตแห่งขุนเขายิ้มและสั่นกระดิ่งวัวใบใหญ่ก้องไปทั่วหุบเขา",
    },
    {
        "en": "That night, fireflies and alpenglow lit the way home for the two friends.",
        "th": "คืนนั้น หิ่งห้อยและแสงสนธยาแห่งเทือกเขาส่องทางกลับบ้านให้เพื่อนรักทั้งสอง",
    },
    {
        "en": "And so the Alps and the river kingdom were friends forever after.",
        "th": "และแล้วเทือกเขาแอลป์กับอาณาจักรแม่น้ำก็เป็นมิตรกันตลอดกาล",
    },
]

_PHRASES: list[str] = [
    "Heidi the marmot waves from a flower meadow",
    "Nari the naga curls around a snowy pine",
    "the mountain spirit rings a giant cowbell",
    "a floating market appears in the alpine lake",
    "fireflies dance over the glacier at dusk",
    "the two friends picnic on a chalet balcony",
]

_NAMES: list[str] = [
    "Heidi the Marmot",
    "Nari the Naga",
    "Barry the Mountain Spirit",
    "Mali the Firefly",
    "Ueli the Ibex",
    "Song the River Otter",
]


class MockLLMProvider(LLMProvider):
    """Offline stand-in for a real LLM; deterministic per (prompt, schema, languages)."""

    def __init__(self, languages: Sequence[str] = ("en", "th")) -> None:
        self._languages = list(languages)

    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Build a valid instance of ``schema``; content varies with ``prompt``.

        When the prompt names a page ("page N"), N drives sample selection so
        that different pages are guaranteed different content — not merely
        hash-probably different.
        """
        seed = int.from_bytes(hashlib.sha256(prompt.encode("utf-8")).digest()[:4], "big")
        page_match = re.search(r"\bpage (\d+)\b", prompt, re.IGNORECASE)
        page = int(page_match.group(1)) if page_match else None
        return schema.model_validate(self._build_model_values(schema, seed, page))

    def _build_model_values(
        self, schema: type[BaseModel], seed: int, page: int | None = None
    ) -> dict[str, object]:
        return {
            name: self._value_for(field.annotation, name, seed, page)
            for name, field in schema.model_fields.items()
            if field.is_required()
        }

    def _value_for(
        self, annotation: object, name: str, seed: int, page: int | None = None
    ) -> object:
        annotation = _unwrap_annotated(annotation)
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)
        salt = seed + sum(name.encode("utf-8"))

        if origin in (typing.Union, types.UnionType):
            return None if type(None) in args else self._value_for(args[0], name, seed, page)
        if annotation is str:
            if name.startswith("name"):
                return _NAMES[salt % len(_NAMES)]
            if page is not None:
                phrase = _PHRASES[(page - 1 + sum(name.encode("utf-8"))) % len(_PHRASES)]
                return f"{phrase.capitalize()} ({name.replace('_', ' ')}, page {page})."
            return f"{_PHRASES[salt % len(_PHRASES)].capitalize()} ({name.replace('_', ' ')})."
        if annotation is int:
            return 1
        if annotation is float:
            return 1.0
        if annotation is bool:
            return False
        if annotation is Path:
            return Path("mock") / name
        if origin is typing.Literal:
            return args[0]
        if origin is dict and args == (str, str):
            index = (page - 1) % len(_TEXTS) if page is not None else salt % len(_TEXTS)
            sample = _TEXTS[index]
            suffix = f" ({page})" if page is not None and page > len(_TEXTS) else ""
            return {
                lang: sample.get(lang, f"[{lang}] Once upon a time, in a faraway land.") + suffix
                for lang in self._languages
            }
        if origin is list:
            if name == "languages":
                return list(self._languages)
            return [self._value_for(args[0], name, seed + i, page) for i in range(1, 4)]
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return self._build_model_values(annotation, seed, page)
        raise KBError(f"mock LLM cannot synthesize a value for field {name!r} ({annotation!r})")


def _unwrap_annotated(annotation: object) -> object:
    while typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    return annotation
