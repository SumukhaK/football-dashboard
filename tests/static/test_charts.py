"""Checks on the one charts script the shell loads.

The redesign moved every colour into ``tokens.css`` and made the theme a runtime
switch, so the script has to name tokens both themes resolve and to redraw on
the events the shell fires. The two branches that met in ``charts.js`` each
brought charts of their own, so these checks also pin the initialisers, the
triggers and the disposal a later merge could drop.

They read the shipped script and the shipped tokens. Whether the redraw really
works — no leaked instance after a swap, none after a theme change — is verified
in a browser, which no Python test here can do.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "app" / "static"
CHARTS = STATIC / "charts.js"
TOKENS = STATIC / "css" / "tokens.css"

# The palette the redesign removed: a caller left on one of these follows
# neither theme.
LEGACY_TOKENS = (
    "--primary-color",
    "--ok-fg",
    "--warn-fg",
    "--bad-fg",
    "--none-fg",
    "--card-bg",
)

INITIALISERS = (
    "initOverviewCharts",
    "initSparklines",
    "initAssistantCharts",
    "initAccessCharts",
)

TRIGGERS = (
    'addEventListener("DOMContentLoaded", init)',
    'addEventListener("htmx:afterSwap", init)',
    'addEventListener("themechange", init)',
)

RENDER = re.compile(
    r"function render\(elementId, option\)\s*\{(?P<body>.*?)\n  \}", re.DOTALL
)
INIT = re.compile(r"function init\(\)\s*\{(?P<body>[^}]*)\}")


def _script() -> str:
    """The shipped charts script."""
    return CHARTS.read_text(encoding="utf-8")


def _themes() -> dict[str, set[str]]:
    """The tokens each theme resolves: light inherits whatever it does not reset."""
    blocks: dict[str, set[str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", TOKENS.read_text("utf-8")):
        name = "light" if 'theme="light"' in selector else "dark"
        blocks[name] = set(re.findall(r"(--[\w-]+)\s*:", body))
    return {"dark": blocks["dark"], "light": blocks["dark"] | blocks["light"]}


def test_every_token_the_charts_name_is_declared_in_both_themes() -> None:
    """A token only one theme resolves would leave a chart unstyled after a switch."""
    named = set(re.findall(r'cssVar\("(--[\w-]+)"\)', _script()))
    assert named, "the script names no tokens at all"
    for theme, declared in _themes().items():
        assert named <= declared, f"{theme} misses {sorted(named - declared)}"


def test_no_legacy_palette_token_survives_in_the_charts() -> None:
    """A chart still asking for the old palette would draw in a colour no theme sets."""
    script = _script()
    found = [name for name in LEGACY_TOKENS if name in script]
    assert not found, found


def test_the_one_initialiser_keeps_every_chart() -> None:
    """Both branches' charts redraw from the same initialiser."""
    match = INIT.search(_script())
    assert match is not None
    for name in INITIALISERS:
        assert re.search(rf"\b{name}\(\);", match.group("body")), name


def test_the_one_initialiser_answers_every_trigger() -> None:
    """The first load, an HTMX swap and a theme change all redraw the charts."""
    script = _script()
    for trigger in TRIGGERS:
        assert trigger in script, trigger


def test_a_render_disposes_the_previous_instance_and_frees_a_replaced_one() -> None:
    """A second render, or a swap, must not leave an instance behind."""
    script = _script()
    match = RENDER.search(script)
    assert match is not None
    body = match.group("body")
    assert "getInstanceByDom(element)" in body
    assert body.index("dispose()") < body.index("echarts.init(element)")
    assert "function disposeDetached()" in script
    initialiser = INIT.search(script)
    assert initialiser is not None
    assert "disposeDetached();" in initialiser.group("body")
