"""Suite-wide defaults for the plugin repository.

Mirrors the platform's ``tests/conftest.py``, and exists for the same reason.

``FORGE_AUTH`` defaults to ``required`` in the product, so every request to a
non-exempt route needs a principal. The platform turned it **off** for its own
suite when authentication shipped (warpforge #82) so that the several hundred
tests written before it kept exercising what they were written to exercise.
This repository never got the same treatment, and nothing noticed: these tests
run against an *installed* platform, so the change landed in a different repo
from the suite it broke, and CI here is not the CI that gated that PR.

The result was 32 failures — every test that touches an authenticated route,
across matter, pendulum and the whole SAGE vertical slice — all reporting
``401`` where they asserted a real status code. They had been red since
2026-07-30 while the READMEs on both sides said the cross-repo suite passed.

Authentication is tested where it belongs: in the platform, by
``tests/integration/test_auth.py``, which sets ``FORGE_AUTH=required`` and
drives the real gate. A plugin has no business re-testing it — but a plugin
whose tests silently stop reaching their own routes is worse than one that
skips them loudly, which is why this is a default rather than a per-test edit.

Mark a test ``auth`` to opt out and manage the variable yourself.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _auth_off_by_default(monkeypatch, request):
    if request.node.get_closest_marker("auth"):
        return                      # the test sets FORGE_AUTH itself
    monkeypatch.setenv("FORGE_AUTH", "off")
