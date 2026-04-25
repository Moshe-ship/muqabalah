"""Core balance() / unbalance() with audit trail.

Properties guaranteed:
  1. Reversibility: unbalance(balance(p, ctx).output, trace) == p
  2. Conflict-loud: contradictions raise CancellationConflict — never silently
     resolved. The agent must explicitly decide.
  3. Trace preserves removed text: every cancellation records the EXACT
     removed substring, its span, and a reason.
  4. Determinism: given the same (prompt, context, detectors), output is
     identical across runs.

The discipline: balance() may only REMOVE or NORMALIZE; it must never
INFER content that was not present. If two phrases conflict and one must be
chosen over the other, balance() refuses and surfaces the conflict.
"""

from __future__ import annotations
import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


class CancellationError(Exception):
    """Generic balance() error."""


class CancellationConflict(CancellationError):
    """Raised when irreconcilable contradictions are detected.

    Carries the conflicting spans for the caller to surface.
    """

    def __init__(self, message: str, conflicts: list[dict[str, Any]]):
        super().__init__(message)
        self.conflicts = conflicts


@dataclass(frozen=True)
class CancellationContext:
    """Inputs that detectors consult.

    user_normalizations: domain-specific normalizations the user supplies
        (e.g., {"USA": "United States", "u.s.": "United States"}).
    contradiction_predicates: list of (a, b) string-pairs that should be
        flagged as contradictory if both appear. Caller-defined.
    """

    user_normalizations: dict[str, str] = field(default_factory=dict)
    contradiction_predicates: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_normalizations": dict(self.user_normalizations),
            "contradiction_predicates": [list(p) for p in self.contradiction_predicates],
        }


@dataclass(frozen=True)
class CancellationEntry:
    """One cancellation recorded in the trace.

    For DUPLICATE: kept_span is the surviving copy; removed_span/removed_text
    is what was discarded.

    For NORMALIZATION: kept_span is the canonical form's span in the output;
    removed_span/removed_text records the original (different) wording in
    the input. The "removal" here is the swap.

    Either way, the trace lets unbalance() restore the original input.
    """

    entry_id: str
    kind: str
    removed_span: tuple[int, int]   # span in INPUT
    removed_text: str               # exact text from INPUT
    kept_text: str                  # what appears in OUTPUT (may equal removed for pure-duplicate kept-form)
    insertion_offset: int           # byte offset in OUTPUT where kept_text starts (for unbalance)
    source: str
    rationale: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "removed_span": list(self.removed_span),
            "removed_text": self.removed_text,
            "kept_text": self.kept_text,
            "insertion_offset": self.insertion_offset,
            "source": self.source,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CancellationTrace:
    entries: tuple[CancellationEntry, ...]
    input_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "input_hash": self.input_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "CancellationTrace":
        d = json.loads(s)
        entries = tuple(
            CancellationEntry(
                entry_id=e["entry_id"],
                kind=e["kind"],
                removed_span=tuple(e["removed_span"]),
                removed_text=e["removed_text"],
                kept_text=e["kept_text"],
                insertion_offset=e["insertion_offset"],
                source=e["source"],
                rationale=e["rationale"],
                confidence=e["confidence"],
            )
            for e in d["entries"]
        )
        return cls(entries=entries, input_hash=d["input_hash"])


@dataclass(frozen=True)
class Balanced:
    input: str
    output: str
    trace: CancellationTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "output": self.output,
            "trace": self.trace.to_dict(),
        }


@dataclass(frozen=True)
class DetectorResult:
    """What a detector returns: actions to apply OR a conflict to raise.

    actions: list of either ("remove_duplicate", removed_span, kept_span,
    rationale, confidence) or ("normalize", span, canonical_form, rationale, confidence).

    conflicts: list of dicts describing contradictions; non-empty conflicts
    cause balance() to raise CancellationConflict before applying any actions.
    """

    actions: list[tuple]
    conflicts: list[dict[str, Any]]


class Detector(Protocol):
    name: str

    def find(
        self,
        input: str,
        context: CancellationContext,
    ) -> DetectorResult:
        ...


def _hash_input(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _make_entry_id(kind: str, span: tuple[int, int], text: str, source: str) -> str:
    payload = f"{kind}|{span[0]},{span[1]}|{text}|{source}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def balance(
    prompt: str,
    context: Optional[CancellationContext] = None,
    detectors: Optional[list[Detector]] = None,
) -> Balanced:
    """Apply Balance (al-muqābalah) to a prompt.

    Returns:
        Balanced — with output (the canonical-form prompt) and trace
        (audit record sufficient for unbalance()).

    Raises:
        CancellationConflict — when contradictions are detected that the
        caller must explicitly resolve. balance() never silently picks.

    Properties:
        unbalance(balance(p, ctx).output, trace) == p (when no conflict)
        Determinism: same (p, ctx, detectors) → same output

    NOTE: The order of detectors matters. ContradictionDetector should
    typically run first to fail-fast on conflicts.
    """
    if context is None:
        context = CancellationContext()
    if detectors is None:
        from muqabalah.detectors import DEFAULT_DETECTORS
        detectors = DEFAULT_DETECTORS

    all_actions: list[tuple] = []
    all_conflicts: list[dict[str, Any]] = []

    for d in detectors:
        result = d.find(prompt, context)
        # Tag actions with detector source if not present
        for a in result.actions:
            all_actions.append(a + (d.name,) if len(a) == 5 else a)
        all_conflicts.extend(result.conflicts)

    if all_conflicts:
        raise CancellationConflict(
            f"Found {len(all_conflicts)} contradiction(s); refusing to silently resolve.",
            all_conflicts,
        )

    # Apply actions left-to-right; track output and trace.
    # Sort actions by removed_span start to apply in reading order.
    all_actions.sort(key=lambda a: a[1][0])

    # Resolve action interactions. Two semantic rules:
    #   1. CONTAINMENT — if action A's span fully contains action B's span,
    #      A subsumes B. B is dropped silently and recorded in the trace
    #      via A's effect. (E.g., a duplicate-sentence removal subsumes a
    #      word-level normalization inside that sentence — the word is
    #      being removed anyway.)
    #   2. PARTIAL OVERLAP — if two actions share spans without one fully
    #      containing the other, that is a true configuration conflict.
    #      Raise CancellationConflict; the caller must reconcile.
    def _spans_overlap(a, b):
        sa, ea = a
        sb, eb = b
        return not (ea <= sb or eb <= sa)

    def _contains(outer, inner):
        return outer[0] <= inner[0] and inner[1] <= outer[1]

    # Drop subsumed (fully-contained) actions
    surviving: list[tuple] = []
    for i, action_i in enumerate(all_actions):
        span_i = action_i[1]
        subsumed = False
        for j, action_j in enumerate(all_actions):
            if i == j:
                continue
            span_j = action_j[1]
            if _contains(span_j, span_i) and span_j != span_i:
                subsumed = True
                break
        if not subsumed:
            surviving.append(action_i)

    # Now check for partial overlaps among survivors
    overlap_conflicts: list[dict[str, Any]] = []
    for i in range(len(surviving)):
        for j in range(i + 1, len(surviving)):
            ai = surviving[i]
            aj = surviving[j]
            si, ei = ai[1]
            sj, ej = aj[1]
            if _spans_overlap(ai[1], aj[1]):
                # Survivors overlap and neither contains the other → partial overlap
                if not (_contains(ai[1], aj[1]) or _contains(aj[1], ai[1])):
                    overlap_conflicts.append({
                        "type": "overlapping_actions",
                        "action_a": {
                            "kind": ai[0], "span": [si, ei],
                            "kept_text": ai[2], "source": ai[5],
                        },
                        "action_b": {
                            "kind": aj[0], "span": [sj, ej],
                            "kept_text": aj[2], "source": aj[5],
                        },
                        "rationale": (
                            f"Detectors {ai[5]!r} and {aj[5]!r} proposed "
                            f"partially-overlapping transformations on spans "
                            f"[{si},{ei}] and [{sj},{ej}]; refusing to choose."
                        ),
                    })
    if overlap_conflicts:
        raise CancellationConflict(
            f"Found {len(overlap_conflicts)} partially-overlapping action conflict(s); "
            f"detectors must produce non-overlapping or fully-containing action proposals.",
            overlap_conflicts,
        )

    all_actions = surviving

    output_parts: list[str] = []
    cursor = 0
    final_entries: list[CancellationEntry] = []

    for action in all_actions:
        kind, removed_span, kept_text, rationale, confidence, source = action
        start, end = removed_span

        # Append literal characters up to the removed span
        output_parts.append(prompt[cursor:start])
        # Track offset of insertion point in output
        prefix_so_far = "".join(output_parts)
        insertion_offset = len(prefix_so_far)

        # Append the kept text in place of the removed span
        output_parts.append(kept_text)

        entry_id = _make_entry_id(kind, removed_span, prompt[start:end], source)
        final_entries.append(CancellationEntry(
            entry_id=entry_id,
            kind=kind,
            removed_span=removed_span,
            removed_text=prompt[start:end],
            kept_text=kept_text,
            insertion_offset=insertion_offset,
            source=source,
            rationale=rationale,
            confidence=confidence,
        ))
        cursor = end

    output_parts.append(prompt[cursor:])
    output = "".join(output_parts)

    trace = CancellationTrace(
        entries=tuple(final_entries),
        input_hash=_hash_input(prompt),
    )

    return Balanced(input=prompt, output=output, trace=trace)


def unbalance(output: str, trace: CancellationTrace) -> str:
    """Reverse Balance — return the original prompt by replacing each
    kept_text in the output with the removed_text from the trace.

    Integrity is verified two ways:
      1. The kept_text at each insertion_offset must match exactly.
      2. The reconstructed input must hash to trace.input_hash.
    """
    if not trace.entries:
        # If trace empty, output should be the original. Verify hash.
        if _hash_input(output) != trace.input_hash:
            raise CancellationError(
                f"Trace integrity failure: empty trace but input hash differs "
                f"(expected {trace.input_hash}, got {_hash_input(output)})"
            )
        return output

    # Sort entries by insertion_offset DESCENDING so we can splice from
    # right-to-left without shifting earlier offsets.
    entries_sorted = sorted(
        trace.entries,
        key=lambda e: e.insertion_offset,
        reverse=True,
    )

    result = output
    for e in entries_sorted:
        start = e.insertion_offset
        end = start + len(e.kept_text)
        # Verify the kept_text is present at insertion_offset (only useful
        # when kept_text is non-empty; for empty kept_text we rely on the
        # final input_hash check)
        if e.kept_text and result[start:end] != e.kept_text:
            raise CancellationError(
                f"Trace integrity failure: expected {e.kept_text!r} at "
                f"offset {start}, found {result[start:end]!r}"
            )
        result = result[:start] + e.removed_text + result[end:]

    # Final hash check — primary integrity gate, especially when entries
    # have empty kept_text.
    if _hash_input(result) != trace.input_hash:
        raise CancellationError(
            f"Trace integrity failure: reconstructed input hash mismatch "
            f"(expected {trace.input_hash}, got {_hash_input(result)})"
        )

    return result
