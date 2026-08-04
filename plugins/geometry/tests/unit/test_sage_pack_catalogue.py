"""The geometry SAGE pack carries the vocabulary the allowlist omits.

A program's `allowed_metric_hashes` is a list of content hashes. That says
which metrics a model may use and nothing about how to address them, and a
live run showed exactly what that costs: given only hashes, the designer
produced a correct three-arm velocity sweep on the right metric and invented
the parameter names, so the plan was rejected at design time. The reasoning
was fine; the vocabulary was missing.
"""

from __future__ import annotations

from forge_geometry.plugin import _metric_catalogue
from forge_metrics import builtin_metrics, load_metric_file


def test_every_bundled_metric_appears_with_its_hash_and_parameters():
    catalogue = _metric_catalogue()

    for name, path in builtin_metrics().items():
        definition = load_metric_file(path).definition
        assert name in catalogue
        assert definition.hash in catalogue          # addressable, exactly
        for parameter in definition.parameters:
            assert f"`{parameter}`" in catalogue


def test_the_warp_parameter_names_a_designer_needs_are_present():
    """The three a live designer got wrong, named explicitly."""
    catalogue = _metric_catalogue()

    for parameter in ("velocity", "radius", "wall_steepness"):
        assert f"`{parameter}`" in catalogue


def test_it_is_generated_from_the_library_not_written_down():
    """A metric added to the plugin must appear without a prose edit."""
    catalogue = _metric_catalogue()

    assert len([n for n in builtin_metrics() if n in catalogue]) == len(builtin_metrics())
    # Truncating the library must change the text — i.e. it is really derived.
    assert catalogue.count("hash `") == len(builtin_metrics())
