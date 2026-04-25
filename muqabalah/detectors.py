"""Built-in detectors for balance().

Each detector is deterministic and independently testable. Detectors return
DetectorResult with actions (apply) and conflicts (fail-loud).
"""

from __future__ import annotations
import re
from typing import Any

from muqabalah.core import DetectorResult, CancellationContext


# --------------------------------------------------------------------------- #
# DuplicateDetector
# --------------------------------------------------------------------------- #


class DuplicateDetector:
    """Detect literal duplicate sentences and remove the repetitions.

    Sentences are split on '.' '?' '!' followed by whitespace. Trailing
    duplicates of an earlier sentence are flagged for removal. The first
    occurrence is kept.
    """

    name = "duplicate"

    _SENT_SPLIT = re.compile(r"([.!?]\s+)")

    def find(
        self,
        input: str,
        context: CancellationContext,
    ) -> DetectorResult:
        # Walk the input by sentences, track seen normalized forms, and
        # produce remove-duplicate actions for repeats.
        actions: list[tuple] = []
        seen: dict[str, tuple[int, int]] = {}  # normalized → first span

        # Reconstruct sentence boundaries with offsets
        offset = 0
        sentences: list[tuple[int, int, str]] = []  # (start, end, text_with_terminator)
        # Use finditer to find sentence terminators
        positions = [0]
        for m in re.finditer(r"[.!?]\s+", input):
            positions.append(m.end())
        positions.append(len(input))

        for i in range(len(positions) - 1):
            start = positions[i]
            end = positions[i + 1]
            if end > start:
                sentences.append((start, end, input[start:end]))

        for start, end, sent_text in sentences:
            # Normalize: strip whitespace, lowercase, remove trailing punct/space
            norm = sent_text.strip().lower()
            norm = re.sub(r"[.!?\s]+$", "", norm)
            if not norm:
                continue
            if norm in seen:
                # Mark this duplicate for removal
                # Remove leading whitespace to keep output tidy
                # (but the removed_text in trace is the exact slice)
                actions.append((
                    "remove_duplicate",
                    (start, end),
                    "",  # kept_text is empty (duplicate fully removed)
                    f"duplicate of sentence at {seen[norm]}",
                    1.0,
                ))
            else:
                seen[norm] = (start, end)

        return DetectorResult(actions=actions, conflicts=[])


# --------------------------------------------------------------------------- #
# NormalizationDetector
# --------------------------------------------------------------------------- #


class NormalizationDetector:
    """Replace user-specified non-canonical forms with their canonical forms.

    Uses context.user_normalizations: e.g., {"USA": "United States"}.

    Only word-bounded matches are replaced. Case-insensitive on the source,
    but the canonical form is inserted exactly as given.
    """

    name = "normalize"

    def find(
        self,
        input: str,
        context: CancellationContext,
    ) -> DetectorResult:
        if not context.user_normalizations:
            return DetectorResult(actions=[], conflicts=[])

        actions: list[tuple] = []
        # Sort longer keys first so longer-form replacements are not eclipsed
        # by shorter prefixes (e.g., "U.S.A." before "U.S.")
        sorted_keys = sorted(
            context.user_normalizations.keys(),
            key=lambda s: -len(s),
        )

        # Track occupied spans to prevent overlapping normalizations
        occupied: list[tuple[int, int]] = []

        def overlaps_existing(span: tuple[int, int]) -> bool:
            for s, e in occupied:
                if not (span[1] <= s or span[0] >= e):
                    return True
            return False

        for key in sorted_keys:
            canonical = context.user_normalizations[key]
            # Boundary handling: require a non-alphanumeric character (or
            # string boundary) on either side. We avoid `\b` because it
            # interacts badly with non-word characters like '.' that are
            # common in abbreviations (e.g. "U.S.A.").
            esc = re.escape(key)
            pattern = r"(?:^|(?<=[^A-Za-z0-9_]))" + esc + r"(?=[^A-Za-z0-9_]|$)"
            for m in re.finditer(pattern, input, flags=re.IGNORECASE):
                span = (m.start(), m.end())
                if overlaps_existing(span):
                    continue
                # If the matched text is already exactly the canonical form,
                # don't bother adding an action (no-op).
                if input[m.start():m.end()] == canonical:
                    continue
                actions.append((
                    "normalize",
                    span,
                    canonical,  # kept_text
                    f"normalize {input[m.start():m.end()]!r} → {canonical!r}",
                    1.0,
                ))
                occupied.append(span)

        return DetectorResult(actions=actions, conflicts=[])


# --------------------------------------------------------------------------- #
# ContradictionDetector
# --------------------------------------------------------------------------- #


class ContradictionDetector:
    """Detect contradictory phrase pairs and FAIL LOUD.

    context.contradiction_predicates is a list of (a, b) tuples. If both 'a'
    and 'b' appear in the input as word-bounded phrases, this detector
    raises a CancellationConflict via the conflicts list.

    This detector NEVER returns actions — it only returns conflicts. The
    architectural commitment is that balance() refuses to silently pick a
    side. The caller must explicitly resolve.
    """

    name = "contradiction"

    def find(
        self,
        input: str,
        context: CancellationContext,
    ) -> DetectorResult:
        if not context.contradiction_predicates:
            return DetectorResult(actions=[], conflicts=[])

        conflicts: list[dict[str, Any]] = []
        lower_input = input.lower()

        for a, b in context.contradiction_predicates:
            a_pattern = r"\b" + re.escape(a.lower()) + r"\b"
            b_pattern = r"\b" + re.escape(b.lower()) + r"\b"
            a_matches = [(m.start(), m.end()) for m in re.finditer(a_pattern, lower_input)]
            b_matches = [(m.start(), m.end()) for m in re.finditer(b_pattern, lower_input)]
            if a_matches and b_matches:
                conflicts.append({
                    "predicate_a": a,
                    "predicate_b": b,
                    "a_spans": [list(s) for s in a_matches],
                    "b_spans": [list(s) for s in b_matches],
                    "rationale": f"Both '{a}' and '{b}' appear; cannot canonicalize without explicit choice",
                })

        return DetectorResult(actions=[], conflicts=conflicts)


# Default detector ordering: contradiction first (fail-fast),
# then normalize, then duplicate.
DEFAULT_DETECTORS = [
    ContradictionDetector(),
    NormalizationDetector(),
    DuplicateDetector(),
]
