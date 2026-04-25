"""Hypothesis-based property tests for muqabalah."""

from __future__ import annotations
from string import ascii_letters

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

from muqabalah.core import (
    balance, unbalance,
    CancellationContext, CancellationConflict,
)
from muqabalah.detectors import (
    DuplicateDetector, NormalizationDetector,
)


# Strategy: arbitrary printable Unicode strings including bracket-like and
# punctuation characters that could trip up sentence segmentation.
ADVERSARIAL_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Zs"),
    ),
    min_size=0,
    max_size=200,
)


@st.composite
def cancellation_contexts(draw):
    """Random CancellationContext."""
    norm_keys = draw(st.lists(
        st.text(alphabet=ascii_letters, min_size=1, max_size=8),
        min_size=0, max_size=3, unique=True,
    ))
    norm = {
        k: draw(st.text(alphabet=ascii_letters, min_size=1, max_size=10))
        for k in norm_keys
    }
    contradiction_pairs = draw(st.lists(
        st.tuples(
            st.text(alphabet=ascii_letters, min_size=2, max_size=8),
            st.text(alphabet=ascii_letters, min_size=2, max_size=8),
        ),
        min_size=0, max_size=2,
    ))
    return CancellationContext(
        user_normalizations=norm,
        contradiction_predicates=contradiction_pairs,
    )


# --- The central reversibility property ----------------------------------


@given(prompt=ADVERSARIAL_TEXT, context=cancellation_contexts())
@settings(max_examples=300, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_reversibility_arbitrary_text(prompt, context):
    """For arbitrary inputs, balance+unbalance recovers the original
    whenever balance succeeds (no contradiction)."""
    try:
        result = balance(prompt, context)
    except CancellationConflict:
        # Conflict prevented balancing; reversibility property doesn't apply.
        return
    recovered = unbalance(result.output, result.trace)
    assert recovered == prompt, (
        f"Reversibility failed for prompt={prompt!r}\n"
        f"  output={result.output!r}\n"
        f"  recovered={recovered!r}"
    )


# --- Determinism property ------------------------------------------------


@given(prompt=ADVERSARIAL_TEXT, context=cancellation_contexts())
@settings(max_examples=200, deadline=None,
          suppress_health_check=[HealthCheck.too_slow])
def test_determinism(prompt, context):
    """Same (prompt, context) → byte-identical output and trace, OR
    the same conflict is raised."""
    try:
        r1 = balance(prompt, context)
    except CancellationConflict as e1:
        # The same call should raise the same way
        with pytest.raises(CancellationConflict):
            balance(prompt, context)
        return
    r2 = balance(prompt, context)
    assert r1.output == r2.output
    assert r1.trace.to_json() == r2.trace.to_json()


# --- Conflict surfacing --------------------------------------------------


@given(
    a=st.text(alphabet=ascii_letters, min_size=3, max_size=8),
    b=st.text(alphabet=ascii_letters, min_size=3, max_size=8),
    sep=st.sampled_from([" and ", " then ", " also "]),
)
@settings(max_examples=100, deadline=None)
def test_contradiction_always_raises(a, b, sep):
    """When both predicates are present and configured as contradictory,
    balance must raise CancellationConflict."""
    if a.lower() == b.lower():
        return
    prompt = f"send to {a}{sep}send to {b}"
    context = CancellationContext(contradiction_predicates=[(a.lower(), b.lower())])
    with pytest.raises(CancellationConflict) as exc_info:
        balance(prompt, context)
    err = exc_info.value
    assert any(
        c.get("predicate_a", "").lower() == a.lower() and
        c.get("predicate_b", "").lower() == b.lower()
        for c in err.conflicts
    )


# --- Overlapping detector outputs raise ----------------------------------


def test_overlapping_actions_raise():
    """If two normalizations would overlap on the same span, raise rather
    than silently picking one."""
    # Normalization rules with overlapping matches: "U.S." → "USA",
    # "U.S.A." → "United States". Both match "U.S.A." → spans overlap.
    prompt = "I'm in U.S.A. now"
    context = CancellationContext(
        user_normalizations={
            "U.S.": "USA",
            "U.S.A.": "United States",
        }
    )
    # The NormalizationDetector itself sorts by length and picks longer first,
    # avoiding internal overlap. To force the conflict, run two separate
    # detectors that disagree.
    nd_a = NormalizationDetector()
    nd_b = NormalizationDetector()
    # Both will produce the same action; that's not overlap, that's duplicate.
    # For a real overlap, simulate by configuring detectors with conflicting
    # rules. Since the built-in detectors handle this internally, we verify
    # the engine catches CROSS-DETECTOR overlaps via a synthetic case.

    # Synthetic test: feed the engine two detector instances that produce
    # overlapping spans for the same input.
    class OverlapA:
        name = "overlap_a"
        def find(self, input, context):
            from muqabalah.core import DetectorResult
            return DetectorResult(
                actions=[("normalize", (0, 3), "ABC", "rule_a", 1.0)],
                conflicts=[],
            )

    class OverlapB:
        name = "overlap_b"
        def find(self, input, context):
            from muqabalah.core import DetectorResult
            return DetectorResult(
                actions=[("normalize", (1, 4), "XYZ", "rule_b", 1.0)],
                conflicts=[],
            )

    with pytest.raises(CancellationConflict) as exc_info:
        balance("HELLO", context, detectors=[OverlapA(), OverlapB()])
    err = exc_info.value
    assert any(c.get("type") == "overlapping_actions" for c in err.conflicts)
