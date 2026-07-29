"""Integration tests run against an *installed* platform.

These exercise the cross-repository contract: forge-platform provides the
services and the governed loop, forge-experiments provides the domains, and
they meet only through `forge.plugins` entry points.  Tests import each
other's fixtures (the Casimir genome), so the directory is on the path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
