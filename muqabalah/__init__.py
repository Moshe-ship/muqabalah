"""muqabalah — reversible cancellation and normalization.

The Balance operation: take a prompt with duplications, redundancies, or
contradictions and return a canonical form with explicit audit trail.
Contradictions are fail-loud — never silently resolved.
"""

from muqabalah.core import (
    balance,
    unbalance,
    Balanced,
    CancellationTrace,
    CancellationEntry,
    CancellationContext,
    CancellationError,
    CancellationConflict,
    Detector,
    DetectorResult,
)
from muqabalah.detectors import (
    DuplicateDetector,
    NormalizationDetector,
    ContradictionDetector,
    DEFAULT_DETECTORS,
)

__version__ = "0.1.0"
__all__ = [
    "balance",
    "unbalance",
    "Balanced",
    "CancellationTrace",
    "CancellationEntry",
    "CancellationContext",
    "CancellationError",
    "CancellationConflict",
    "Detector",
    "DuplicateDetector",
    "NormalizationDetector",
    "ContradictionDetector",
    "DEFAULT_DETECTORS",
]
