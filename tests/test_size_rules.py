"""The repository's size rules: no file over 400 lines, no function over 40.

The guides have always stated both limits; this test is what keeps them true.
Split by behaviour when either fails, rather than raising the limit.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from app.config import REPO_ROOT

MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 40
SOURCE_DIRS = ("app", "tests", "deploy", "scripts")
SUFFIXES = {".py", ".html", ".css", ".js", ".sh"}


def _source_files() -> Iterator[Path]:
    """Every checked file under the source directories, caches left out."""
    for top in SOURCE_DIRS:
        for path in sorted((REPO_ROOT / top).rglob("*")):
            if path.suffix in SUFFIXES and "__pycache__" not in path.parts:
                yield path


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_the_rules_see_every_kind_of_source_file() -> None:
    """A walk that silently found nothing would pass every rule."""
    found = {path.suffix for path in _source_files()}

    assert found == SUFFIXES


def test_no_source_file_is_over_400_lines() -> None:
    """Long files are split by behaviour, not allowed to grow."""
    over = {
        str(path.relative_to(REPO_ROOT)): lines
        for path in _source_files()
        if (lines := _line_count(path)) > MAX_FILE_LINES
    }

    assert over == {}


def test_no_python_function_is_over_40_lines() -> None:
    """Measured from the ``def`` line to the last line, docstring included."""
    over = {}
    for path in _source_files():
        if path.suffix != ".py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                if length > MAX_FUNCTION_LINES:
                    name = f"{path.relative_to(REPO_ROOT)}:{node.name}"
                    over[name] = length

    assert over == {}
