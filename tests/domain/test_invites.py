"""Tests for invite codes and emails, against the platform backend's format."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

import pytest

from app.domain.invites import (
    ALPHABET,
    InvalidEmailError,
    code_hash,
    new_code,
    normalise_code,
    normalise_email,
)

K7MPW3QX_HASH = hashlib.sha256(b"K7MPW3QX").hexdigest()


@pytest.mark.parametrize("code", ["K7MP-W3QX", " k7mp w3qx ", "K7MPW3QX"])
def test_code_hash_matches_the_backend_vector(code: str) -> None:
    """Every way of typing the code hashes to sha256 of the bare upper-case code."""
    assert code_hash(code) == K7MPW3QX_HASH


def test_normalise_code_drops_spaces_and_dashes() -> None:
    """Normalising leaves only the eight upper-case characters."""
    assert normalise_code(" k7mp-w3 qx ") == "K7MPW3QX"


def test_new_code_uses_the_injected_choice_and_groups_by_four() -> None:
    """Characters come from the injected choice and show as XXXX-XXXX."""
    letters: Iterator[str] = iter("K7MPW3QX")
    assert new_code(lambda alphabet: next(letters)) == "K7MP-W3QX"


def test_new_code_only_draws_from_the_alphabet() -> None:
    """The choice is offered the unambiguous alphabet, once per character."""
    offered: list[str] = []

    def choose(alphabet: str) -> str:
        offered.append(alphabet)
        return alphabet[0]

    assert new_code(choose) == "AAAA-AAAA"
    assert offered == [ALPHABET] * 8


def test_default_code_has_the_shown_format() -> None:
    """The secrets-backed default produces XXXX-XXXX from the alphabet."""
    pattern = f"[{ALPHABET}]{{4}}-[{ALPHABET}]{{4}}"
    assert re.fullmatch(pattern, new_code())


def test_alphabet_leaves_out_lookalike_characters() -> None:
    """No I, L, O, U, 0 or 1, which are easy to misread."""
    assert ALPHABET == "ABCDEFGHJKMNPQRSTVWXYZ23456789"


def test_normalise_email_strips_and_lowers() -> None:
    """The document id is the trimmed, lower-case email."""
    assert normalise_email("  Ann@Example.COM ") == "ann@example.com"


@pytest.mark.parametrize(
    "email",
    ["", "ann", "@example.com", "ann@", "a@b@c.com", "a b@c.com", "a/b@c.com"],
)
def test_normalise_email_rejects_bad_addresses(email: str) -> None:
    """One @, both parts present, no spaces and no slash."""
    with pytest.raises(InvalidEmailError):
        normalise_email(email)
