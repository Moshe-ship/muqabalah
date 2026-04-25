"""Core tests for balance() / unbalance()."""

from __future__ import annotations
import pytest

from muqabalah.core import (
    balance, unbalance,
    CancellationContext, CancellationTrace,
    CancellationConflict, CancellationError,
)


def ctx(**overrides):
    return CancellationContext(**overrides)


# --- Reversibility --------------------------------------------------------


def test_roundtrip_no_actions():
    p = "hello world"
    r = balance(p, ctx())
    assert r.output == p
    assert unbalance(r.output, r.trace) == p


def test_roundtrip_normalization():
    p = "I live in usa and travel to USA often."
    c = ctx(user_normalizations={"usa": "United States"})
    r = balance(p, c)
    assert "United States" in r.output
    assert unbalance(r.output, r.trace) == p


def test_roundtrip_duplicate_removal():
    p = "Send the report. Send the report."
    r = balance(p, ctx())
    # First sentence kept, second removed
    assert r.output.lower().count("send the report") == 1
    assert unbalance(r.output, r.trace) == p


def test_roundtrip_normalization_and_duplicate():
    p = "I live in u.s. I live in u.s."
    c = ctx(user_normalizations={"u.s.": "United States"})
    r = balance(p, c)
    assert unbalance(r.output, r.trace) == p


# --- Determinism ----------------------------------------------------------


def test_determinism():
    p = "Send. Send. Send."
    r1 = balance(p, ctx())
    r2 = balance(p, ctx())
    assert r1.output == r2.output
    assert r1.trace.to_json() == r2.trace.to_json()


# --- Contradiction handling (fail-loud) -----------------------------------


def test_contradiction_raises():
    p = "Send to alice and send to bob"
    c = ctx(contradiction_predicates=[("alice", "bob")])
    with pytest.raises(CancellationConflict) as exc_info:
        balance(p, c)
    err = exc_info.value
    assert len(err.conflicts) == 1
    assert err.conflicts[0]["predicate_a"] == "alice"
    assert err.conflicts[0]["predicate_b"] == "bob"


def test_contradiction_no_match_does_not_raise():
    p = "Send to alice"
    c = ctx(contradiction_predicates=[("alice", "bob")])
    # Only alice present; not a conflict
    r = balance(p, c)
    assert r.output == p


def test_multiple_contradictions_all_reported():
    p = "left and right and up and down"
    c = ctx(contradiction_predicates=[
        ("left", "right"),
        ("up", "down"),
    ])
    with pytest.raises(CancellationConflict) as exc_info:
        balance(p, c)
    assert len(exc_info.value.conflicts) == 2


# --- Trace integrity ------------------------------------------------------


def test_trace_records_removed_text():
    p = "go now. go now."
    r = balance(p, ctx())
    assert len(r.trace.entries) == 1
    assert r.trace.entries[0].removed_text.strip().lower() == "go now."


def test_unbalance_with_wrong_trace_raises():
    p1 = "alpha. alpha."
    p2 = "beta. beta."
    r1 = balance(p1, ctx())
    r2 = balance(p2, ctx())
    with pytest.raises(CancellationError):
        unbalance(r1.output, r2.trace)


def test_trace_json_roundtrip():
    p = "the meeting is at 9am. the meeting is at 9am."
    r = balance(p, ctx())
    j = r.trace.to_json()
    restored = CancellationTrace.from_json(j)
    assert restored == r.trace


# --- Edge cases -----------------------------------------------------------


def test_empty_string():
    r = balance("", ctx())
    assert r.output == ""
    assert r.trace.entries == ()


def test_normalization_skips_when_already_canonical():
    """If the input already contains the canonical form, no-op."""
    p = "United States is large"
    c = ctx(user_normalizations={"usa": "United States"})
    r = balance(p, c)
    assert r.output == p
    assert len(r.trace.entries) == 0


def test_normalization_word_boundary():
    """Don't replace 'us' inside 'use'."""
    p = "I want to use it"
    c = ctx(user_normalizations={"us": "United States"})
    r = balance(p, c)
    # 'us' inside 'use' should not match (word boundary)
    assert r.output == p


def test_overlap_skipped():
    """Two normalizations on overlapping spans: longer wins."""
    p = "The U.S.A. is large"
    c = ctx(user_normalizations={"U.S.A.": "United States",
                                  "U.S.": "U.S."})
    r = balance(p, c)
    # The longer match should be applied
    assert "United States" in r.output


# --- Specific kinds -------------------------------------------------------


def test_duplicate_kind_marked():
    p = "Hello. Hello."
    r = balance(p, ctx())
    assert r.trace.entries[0].kind == "remove_duplicate"


def test_normalize_kind_marked():
    p = "I'm in usa"
    c = ctx(user_normalizations={"usa": "United States"})
    r = balance(p, c)
    assert r.trace.entries[0].kind == "normalize"


# --- Confidence -----------------------------------------------------------


def test_normalization_confidence_is_full():
    p = "I'm in usa"
    c = ctx(user_normalizations={"usa": "United States"})
    r = balance(p, c)
    assert r.trace.entries[0].confidence == 1.0


def test_duplicate_confidence_is_full():
    p = "Yes. Yes."
    r = balance(p, ctx())
    assert r.trace.entries[0].confidence == 1.0
