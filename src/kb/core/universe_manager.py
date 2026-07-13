"""Universe management: reusable story settings under ``Global/universes/``."""

from __future__ import annotations

from pathlib import Path

from kb.core.models import Universe
from kb.core.persistence import atomic_write_yaml, read_yaml
from kb.errors import NotFoundError


class UniverseManager:
    """Creates and loads universes, one ``universe.yaml`` per slug directory."""

    def __init__(self, universes_dir: Path) -> None:
        self._universes_dir = universes_dir

    def _file(self, slug: str) -> Path:
        return self._universes_dir / slug / "universe.yaml"

    def exists(self, slug: str) -> bool:
        return self._file(slug).is_file()

    def list_slugs(self) -> list[str]:
        if not self._universes_dir.is_dir():
            return []
        return sorted(
            p.name for p in self._universes_dir.iterdir() if (p / "universe.yaml").is_file()
        )

    def load(self, slug: str) -> Universe:
        if not self.exists(slug):
            raise NotFoundError(f"unknown universe: {slug!r}")
        return Universe.model_validate(read_yaml(self._file(slug)))

    def load_all(self) -> list[Universe]:
        return [self.load(slug) for slug in self.list_slugs()]

    def create(
        self,
        *,
        slug: str,
        name: str,
        languages: list[str],
        description: str = "",
        style_guide: str = "",
    ) -> Universe:
        universe = Universe(
            slug=slug,
            name=name,
            languages=languages,
            description=description,
            style_guide=style_guide,
        )
        atomic_write_yaml(self._file(slug), universe.model_dump(mode="json"))
        return universe
