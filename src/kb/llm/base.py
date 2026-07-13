"""Abstract LLM provider interface (HC-5.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Swappable LLM client. Concrete providers own their credentials (HC-5.3)."""

    @abstractmethod
    def generate_structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Return a response validated against ``schema`` (structured outputs, HC-1.1).

        Implementations must re-prompt with validation errors on invalid output
        (at most 2 corrective attempts, spec §7.2) and raise ``KBError`` on failure.
        """
