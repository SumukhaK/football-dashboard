"""Scope and filter forms never show a value the page is not using.

Private pages are no-store, so Back re-fetches them, but a browser still
restores the previous values of form controls unless the form opts out. The
release selector then showed 2.6.0 over an all-releases page, and Apply would
silently re-apply it. Every GET form therefore carries ``autocomplete="off"``.
"""

from __future__ import annotations

import re

import pytest

from tests.auth.console import console

FORM = re.compile(r"<form\b[^>]*>", re.DOTALL)


@pytest.mark.parametrize(
    "path", ["/", "/errors", "/requests", "/requests?tab=logs", "/crashes"]
)
def test_every_get_form_opts_out_of_restored_values(path: str) -> None:
    """A Back to this page renders the server's scope, not the last one typed."""
    html = console().client.get(path).text
    forms = [tag for tag in FORM.findall(html) if 'method="post"' not in tag]

    assert forms
    assert [tag for tag in forms if 'autocomplete="off"' not in tag] == []
