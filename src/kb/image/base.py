"""Abstract image provider interface enforcing the reference cap (HC-2.2, HC-5.2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Final

MAX_TOTAL_REFERENCES: Final = 4  # HC-2.2


class ImageProvider(ABC):
    """Swappable image client. Concrete providers own their credentials (HC-5.3)."""

    async def generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        references: Sequence[Path] = (),
        size: int = 1024,
    ) -> Path:
        """Generate an image; enforces the hard reference-image cap at the boundary."""
        if len(references) > MAX_TOTAL_REFERENCES:
            raise ValueError(
                f"{len(references)} reference images exceed the hard cap of "
                f"{MAX_TOTAL_REFERENCES} (HC-2.2)"
            )
        return await self._generate(
            prompt=prompt, out_path=out_path, references=references, size=size
        )

    @abstractmethod
    async def _generate(
        self,
        *,
        prompt: str,
        out_path: Path,
        references: Sequence[Path],
        size: int,
    ) -> Path:
        """Provider-specific generation; ``references`` is already validated."""
