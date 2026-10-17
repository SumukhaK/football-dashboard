"""Static checks on the design tokens: contrast, and where colours may live.

The contrast maths is WCAG 2.1 relative luminance, written out here so the test
needs no library. The tokens file is the only file allowed to hold a colour.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CSS_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "css"
FONT_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "fonts"
TOKENS = CSS_DIR / "tokens.css"
COMPONENTS = CSS_DIR / "components.css"

# WCAG AA for normal text.
REQUIRED = 4.5

# Every text token has to be readable on all three grounds of its theme.
TEXT_TOKENS = ("--ink", "--ink-2", "--muted", "--faint", "--accent")
GROUNDS = ("--bg", "--surface", "--surface-2")

TONES = ("fail", "warn", "ok", "accent", "neutral", "purple")

FONTS = (
    "IBMPlexSans-Regular.woff2",
    "IBMPlexSans-Medium.woff2",
    "IBMPlexSans-SemiBold.woff2",
    "IBMPlexMono-Regular.woff2",
    "IBMPlexMono-Medium.woff2",
    "IBMPLEX-LICENSE.txt",
)


def channel(value: int) -> float:
    """One 8-bit sRGB channel as its WCAG relative-luminance term."""
    part = value / 255
    return part / 12.92 if part <= 0.03928 else ((part + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """The WCAG relative luminance of a ``#rrggbb`` colour."""
    red, green, blue = (int(colour[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(one: str, other: str) -> float:
    """The WCAG contrast ratio between two colours, lighter one first."""
    lighter, darker = sorted((luminance(one), luminance(other)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def theme_tokens() -> dict[str, dict[str, str]]:
    """Each theme's tokens: the dark block, then the light block over it."""
    blocks: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", TOKENS.read_text("utf-8")):
        light = 'theme="light"' in selector
        found = dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})", body))
        blocks["light" if light else "dark"] = found
    dark = blocks["dark"]
    return {"dark": dark, "light": {**dark, **blocks["light"]}}


def pill_pairs() -> list[tuple[str, str, str]]:
    """Every pill rule as (tone, text token, background token)."""
    pairs: list[tuple[str, str, str]] = []
    for tone, body in re.findall(
        r"\.pill-(\w+)\s*\{([^}]*)\}", COMPONENTS.read_text("utf-8")
    ):
        text = re.search(r"color:\s*var\((--[\w-]+)\)", body)
        background = re.search(r"background:\s*var\((--[\w-]+)\)", body)
        assert text and background, tone
        pairs.append((tone, text.group(1), background.group(1)))
    return pairs


def test_the_two_themes_declare_the_same_tokens() -> None:
    """The light theme repeats every token the dark theme sets."""
    blocks = theme_tokens()
    assert set(blocks["dark"]) == set(blocks["light"])


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_every_text_token_is_readable_on_every_ground(theme: str) -> None:
    """Ink, muted, faint and accent reach 4.5:1 on each ground."""
    tokens = theme_tokens()[theme]
    for name in TEXT_TOKENS:
        for ground in GROUNDS:
            ratio = contrast(tokens[name], tokens[ground])
            assert ratio >= REQUIRED, f"{theme}: {name} on {ground} is {ratio:.2f}"


@pytest.mark.parametrize("theme", ("dark", "light"))
def test_every_pill_is_readable_on_its_own_background(theme: str) -> None:
    """Each tone's text reaches 4.5:1 on the background that tone paints."""
    tokens = theme_tokens()[theme]
    pairs = pill_pairs()
    assert tuple(tone for tone, _, _ in pairs) == TONES
    for tone, text, background in pairs:
        ratio = contrast(tokens[text], tokens[background])
        assert ratio >= REQUIRED, f"{theme}: {tone} is {ratio:.2f}"


def test_only_the_token_file_holds_a_colour() -> None:
    """A hex colour outside tokens.css could not follow the theme."""
    for path in sorted(CSS_DIR.glob("*.css")):
        if path == TOKENS:
            continue
        found = re.findall(r"#[0-9A-Fa-f]{3,8}", path.read_text("utf-8"))
        assert not found, f"{path.name} holds {found}"


def test_the_plex_fonts_are_vendored_with_their_licence() -> None:
    """The fonts are static files next to their SIL Open Font License."""
    for name in FONTS:
        assert (FONT_DIR / name).is_file(), name


def test_the_shell_declares_every_font_it_ships() -> None:
    """Each vendored face is declared once, from this server, not a CDN."""
    shell = (CSS_DIR / "shell.css").read_text("utf-8")
    assert shell.count("@font-face") == 5
    assert "fonts.gstatic.com" not in shell
    for name in (name for name in FONTS if name.endswith(".woff2")):
        assert f'url("/static/fonts/{name}")' in shell, name
