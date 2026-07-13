"""Deterministic offline LLM provider for development, tests, and phase gates (§15).

Synthesizes schema-valid Pydantic instances by introspecting the target model:
no network, no credentials, zero cost. ``dict[str, str]`` fields are filled
with placeholder text for every configured language — including real Thai
text, so the PDF gate exercises libthai line breaking (HC-3.4).
"""

from __future__ import annotations

import types
import typing
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from kb.errors import KBError
from kb.llm.base import LLMProvider, T

_SAMPLE_TEXT = {
    "en": "Once upon a time, a kind little bear lived high in the mountains.",
    "th": "กาลครั้งหนึ่ง หมีน้อยใจดีอาศัยอยู่บนภูเขาสูง",
}


def _sample_text(lang: str) -> str:
    return _SAMPLE_TEXT.get(lang, f"[{lang}] Once upon a time, in a faraway land.")


class MockLLMProvider(LLMProvider):
    """Offline stand-in for a real LLM; output depends only on the schema and languages."""

    def __init__(self, languages: Sequence[str] = ("en", "th")) -> None:
        self._languages = list(languages)

    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Build a valid instance of ``schema``; ``system``/``prompt`` are ignored."""
        return schema.model_validate(self._build_model_values(schema))

    def _build_model_values(self, schema: type[BaseModel]) -> dict[str, object]:
        return {
            name: self._value_for(field.annotation, name)
            for name, field in schema.model_fields.items()
            if field.is_required()
        }

    def _value_for(self, annotation: object, name: str) -> object:
        annotation = _unwrap_annotated(annotation)
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        if origin in (typing.Union, types.UnionType):
            return None if type(None) in args else self._value_for(args[0], name)
        if annotation is str:
            return f"Mock {name.replace('_', ' ')}."
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
            return {lang: _sample_text(lang) for lang in self._languages}
        if origin is list:
            if name == "languages":
                return list(self._languages)
            return [self._value_for(args[0], name)]
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return self._build_model_values(annotation)
        raise KBError(f"mock LLM cannot synthesize a value for field {name!r} ({annotation!r})")


def _unwrap_annotated(annotation: object) -> object:
    while typing.get_origin(annotation) is typing.Annotated:
        annotation = typing.get_args(annotation)[0]
    return annotation
