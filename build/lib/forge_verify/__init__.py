"""forge_verify — independent verification backend (backlog B-2).

A second symbolic path through the tensor chain (metric → frame → connection
→ Riemann → Ricci → Einstein → stress-energy), derived and implemented
independently of ``forge_math.pipeline``, plus the machinery to compare the
two and record what the comparison actually established.

Honest statement of independence — see ``compare.SHARED_CAS_INDEPENDENCE``:
independent implementation *and* independent derivation route, same CAS.
"""

from forge_verify.compare import (
    SHARED_CAS_INDEPENDENCE, AgreementStatus, CrossBackendComparison,
    QuantityComparison, compare_geometries, compare_quantity,
)
from forge_verify.equivalence import (
    EquivalenceCheck, EquivalenceMethod, Verdict, check_equivalent, is_zero,
)
from forge_verify.frame_curvature import (
    FrameGeometry, FrameGeometryError, compute_frame_geometry,
)
from forge_verify.tetrad import Coframe, TetradError, build_coframe

__all__ = [
    "SHARED_CAS_INDEPENDENCE",
    "AgreementStatus",
    "Coframe",
    "CrossBackendComparison",
    "EquivalenceCheck",
    "EquivalenceMethod",
    "FrameGeometry",
    "FrameGeometryError",
    "QuantityComparison",
    "TetradError",
    "Verdict",
    "build_coframe",
    "check_equivalent",
    "compare_geometries",
    "compare_quantity",
    "compute_frame_geometry",
    "is_zero",
]
