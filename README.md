# muqabalah (المقابلة) — Reversible Cancellation + Normalization

> Part of the [**Mizan**](https://github.com/Moshe-ship/mizan) stack — the Arabic-first reliability scale for AI agents.


[![PyPI](https://img.shields.io/pypi/v/muqabalah)](https://pypi.org/project/muqabalah/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![Tests: 19 passing](https://img.shields.io/badge/tests-19%20passing-green.svg)]()

The Balance operation as a standalone primitive. Companion to `jabr`. Reversible. Audited. **Fail-loud on contradiction**.

---

## What it does

Takes a prompt with duplications, redundancies, or contradictions. Produces a canonical form with a full audit trail. The original is recoverable.

**Critically**: contradictions are *never silently resolved*. If two phrases conflict and one would have to be chosen over the other, `balance()` raises `CancellationConflict` and surfaces both options to the caller.

```python
from muqabalah import balance, unbalance, CancellationContext

ctx = CancellationContext(
    user_normalizations={"u.s.": "United States", "usa": "United States"},
    contradiction_predicates=[("alice", "bob")],  # detect conflict
)

# Duplication + normalization
result = balance("I live in u.s. I live in u.s.", ctx)
print(result.output)
# I live in United States.
assert unbalance(result.output, result.trace) == "I live in u.s. I live in u.s."

# Contradiction — raises
try:
    balance("send to alice and send to bob", ctx)
except CancellationConflict as e:
    print(e.conflicts)  # → [{"predicate_a": "alice", "predicate_b": "bob", ...}]
```

## Design properties

1. **Reversibility.** `unbalance(balance(p, ctx).output, trace) == p` whenever `balance` succeeds. Verified by 19 tests.

2. **Fail-loud on conflict.** When contradictions are detected, `balance` raises `CancellationConflict` with all conflicting spans. **The library never picks a side silently.**

3. **Trace integrity.** Every removal records the exact removed text, span, and rationale. `unbalance` verifies both per-entry kept-text and a final `input_hash` round-trip. Wrong traces raise `CancellationError`.

4. **Determinism.** Given the same `(prompt, context, detectors)`, byte-identical output and trace.

## Why fail-loud matters

Modern agent pipelines silently resolve contradictions all the time. A user says "send to A; also send to B" and the agent just picks one. The user never knows. The audit log shows only the chosen action.

`muqabalah` makes contradiction explicit. The agent must decide — and the decision is recorded in a separate step, not buried inside an opaque chain-of-thought.

## Built-in detectors

| Detector | Behavior |
|---|---|
| `ContradictionDetector` | Reports conflicts (no silent resolution); runs first |
| `NormalizationDetector` | Replaces user-defined non-canonical forms with canonical ones |
| `DuplicateDetector` | Removes literal duplicate sentences (keeps first occurrence) |

Add a custom detector:

```python
from muqabalah import Detector, DetectorResult, CancellationContext

class MyDetector:
    name = "my_detector"
    def find(self, input: str, context: CancellationContext) -> DetectorResult:
        # Return DetectorResult(actions=[...], conflicts=[...])
        ...
```

## CLI

```bash
# Balance
muqabalah balance --prompt "..." --context ctx.json

# Round-trip verify
muqabalah roundtrip --prompt "Hello. Hello."

# Reverse balance to original
muqabalah unbalance --output "..." --trace-file trace.json
```

Where `ctx.json` is:

```json
{
  "user_normalizations": {"u.s.": "United States"},
  "contradiction_predicates": [["alice", "bob"]]
}
```

## Install

```bash
pip install muqabalah

# or from a source checkout:
pip install -e .
```

## Tests

```bash
pytest tests/ -v
```

19/19 pass on Python 3.10+. No runtime dependencies.

## What it is not

- Not a paraphraser. `muqabalah` only removes, replaces, or surfaces conflicts. It never rewrites for "clarity" or "tone."
- Not a fact-checker. It detects *self-contradictions* declared by the caller in `contradiction_predicates`. It does not call out to a knowledge base.
- Not a deduplicator for non-sentences. The default `DuplicateDetector` works on sentences. For other granularities, write a custom detector.

## Composition with `jabr`

`jabr` and `muqabalah` are designed to compose:

```python
from jabr import restore
from muqabalah import balance

# Pipeline: restore → balance
restored = restore(prompt, restoration_ctx)
balanced = balance(restored.output, cancellation_ctx)

# Both reversible:
from jabr import unrestore
from muqabalah import unbalance
recovered = unrestore(unbalance(balanced.output, balanced.trace), restored.trace)
assert recovered == prompt
```

## Failure modes

See `FAILURES.md`.

## License

MIT.
