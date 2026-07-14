"""Reference selection tests (HC-2.2, spec §13) and prompt-builder tests (HC-2.3/2.4)."""

from __future__ import annotations

from pathlib import Path

from kb.consistency.prompt_builder import build_page_image_prompt, build_reference_prompt
from kb.consistency.reference_manager import select_references
from kb.core.models import Book, Character, Page, Universe


def _character(index: int, with_reference: bool = True) -> Character:
    return Character(
        slug=f"char-{index}",
        name=f"Character {index}",
        role="hero",
        description=f"Description {index}.",
        visual_keywords=[f"keyword-{index}a", f"keyword-{index}b"],
        primary_reference=Path(f"references/char-{index}.png") if with_reference else None,
    )


def _book(characters: list[Character]) -> Book:
    return Book(
        slug="b", title="B", universe_slug="u", languages=["en", "th"], characters=characters
    )


UNIVERSE = Universe(slug="u", name="U", languages=["en", "th"], style_guide="Warm watercolour.")


def test_hc22_cap_at_four_references_by_salience() -> None:
    """> 4 characters in a scene: only the 4 most salient get references."""
    book = _book([_character(i) for i in range(1, 7)])
    page = Page(number=1, characters_present=[f"char-{i}" for i in range(1, 7)])

    selected = select_references(book, page)

    assert [c.slug for c in selected] == ["char-1", "char-2", "char-3", "char-4"]


def test_hc22_one_reference_per_character_despite_duplicates() -> None:
    book = _book([_character(1), _character(2)])
    page = Page(number=1, characters_present=["char-1", "char-1", "char-2"])

    selected = select_references(book, page)

    assert [c.slug for c in selected] == ["char-1", "char-2"]


def test_hc22_characters_without_reference_are_skipped() -> None:
    book = _book([_character(1, with_reference=False), _character(2)])
    page = Page(number=1, characters_present=["char-1", "char-2"])

    assert [c.slug for c in select_references(book, page)] == ["char-2"]


def test_hc22_unknown_slugs_are_ignored() -> None:
    book = _book([_character(1)])
    page = Page(number=1, characters_present=["ghost", "char-1"])

    assert [c.slug for c in select_references(book, page)] == ["char-1"]


def test_hc23_prompt_binds_each_reference_to_name_and_position() -> None:
    characters = [_character(1), _character(2)]
    page = Page(number=1, image_prompt="Two friends meet by the river.")

    prompt = build_page_image_prompt(UNIVERSE, page, characters)

    assert "Character 1, matching reference image 1" in prompt
    assert "Character 2, matching reference image 2" in prompt
    assert "on the left side of the image" in prompt
    assert "on the right side of the image" in prompt


def test_hc24_prompt_contains_distinct_keywords_and_anti_bleed_clause() -> None:
    characters = [_character(1), _character(2)]
    page = Page(number=1, image_prompt="A scene.")

    prompt = build_page_image_prompt(UNIVERSE, page, characters)

    assert "keyword-1a" in prompt
    assert "keyword-2a" in prompt
    assert "do not blend or mix character identities" in prompt


def test_page_prompt_uses_scene_true_positions_with_fallback() -> None:
    """HC-2.3 anchoring prefers Step 04's scene positions over generic fallbacks."""
    characters = [_character(1), _character(2)]
    page = Page(
        number=1,
        image_prompt="Fritz kneels in the mud.",
        character_positions={"char-1": "kneeling in the mud, centre foreground"},
    )

    prompt = build_page_image_prompt(UNIVERSE, page, characters)

    assert "Character 1, matching reference image 1, is kneeling in the mud" in prompt
    assert "Character 2, matching reference image 2, is on the right side" in prompt  # fallback


def test_page_prompt_is_a_scene_not_a_character_sheet() -> None:
    """Page prompts must frame a story scene and mark references as identity-only."""
    page = Page(number=1, image_prompt="A quiet river at dusk.")

    prompt = build_page_image_prompt(UNIVERSE, page, [_character(1)])

    assert prompt.startswith("A storybook page illustration")
    assert "not a character sheet" in prompt
    assert "IDENTITY only" in prompt
    assert "Do not copy their neutral pose" in prompt
    assert "Scene: A quiet river at dusk." in prompt


def test_no_text_clause_in_page_and_reference_prompts() -> None:
    """Images must never contain rendered text (picture-book pages are text-free)."""
    page_prompt = build_page_image_prompt(
        UNIVERSE, Page(number=1, image_prompt="A scene."), [_character(1)]
    )
    reference_prompt = build_reference_prompt(UNIVERSE, _character(1))

    for prompt in (page_prompt, reference_prompt):
        assert "no written text" in prompt
        assert "speech bubbles" in prompt


def test_full_bleed_clause_in_page_and_reference_prompts() -> None:
    """Print pages are full-bleed (HC-3.2): no frames, margins, or panel layouts."""
    page_prompt = build_page_image_prompt(
        UNIVERSE, Page(number=1, image_prompt="A scene."), [_character(1)]
    )
    reference_prompt = build_reference_prompt(UNIVERSE, _character(1))

    for prompt in (page_prompt, reference_prompt):
        assert "edge to edge" in prompt
        assert "No borders, no frames" in prompt
        assert "no white or black margins" in prompt
    assert "never divide the image into panels" in page_prompt


def test_reference_sheet_prompt_is_neutral_full_body() -> None:
    prompt = build_reference_prompt(UNIVERSE, _character(1))

    assert "full body" in prompt
    assert "neutral standing pose" in prompt
    assert "plain light background" in prompt
    assert "keyword-1a" in prompt
