"""Every list view says something when it is empty.

A table rendered as bare headers, or a picker rendered as an empty dropdown,
is indistinguishable from a view whose data failed to load — and it is the
*first* thing a new installation shows, before anyone has created anything.
Both of ours did exactly that until 2026-08-01.

These are source assertions, which is a weak form of proof: they catch the
empty state being deleted, not the empty state failing to render. The
rendering check is a screenshot against a stack with an empty database, which
is how the two below were confirmed. Keep both — this repository's UI is
plain JS with no test runner, and a guard that only catches deletion is still
worth more than none.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PLUGINS = Path(__file__).resolve().parents[1] / "plugins"

#: (module, a phrase the empty state must contain, what it is the empty state
#: *of*).  The phrases are deliberately the user-facing words rather than
#: markup, so rewording the guidance keeps the test honest by making someone
#: look at it.
CASES = [
    ("matter/forge_matter/ui/matter.js", "No configurations yet",
     "the matter configuration list"),
    ("geometry/forge_geometry/ui/geometry.js", "No runs yet",
     "the geometry results picker"),
]


@pytest.mark.parametrize("module,phrase,what", CASES,
                         ids=[c[2] for c in CASES])
def test_the_list_view_says_when_it_is_empty(module, phrase, what):
    source = (PLUGINS / module).read_text()
    assert phrase in source, (
        f"{what} has no empty state: with no rows it renders as headers over "
        f"nothing, which reads as a load failure rather than as 'you have not "
        f"made one yet'. Say which it is, and say what to click.")


def test_the_empty_state_tells_the_reader_what_to_do():
    """An empty state that only reports emptiness wastes the one moment the
    reader is definitely looking for the next action."""
    matter = (PLUGINS / CASES[0][0]).read_text()
    geometry = (PLUGINS / CASES[1][0]).read_text()
    assert "Create demo plate\n        stack" in matter or \
           "Create demo plate" in matter, \
        "matter's empty state should name the button that fixes it"
    assert "Library" in geometry, \
        "geometry's empty state should name the view a first run starts from"
