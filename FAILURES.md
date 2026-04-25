# FAILURES.md

> Inspired by Abū Bakr al-Rāzī, who wrote a separate book listing his own
> medical failures.

This document tracks known limitations of `muqabalah`.

---

## Things this library deliberately does NOT do

- **No silent contradiction resolution.** If two phrases conflict, `balance` raises `CancellationConflict`. Callers who want a default-resolution policy must implement it explicitly.

- **No semantic deduplication.** "I'm hungry" and "I want food" are not detected as duplicates. The `DuplicateDetector` matches *literal* repetitions only (after lowercase + trim).

- **No contextual paraphrasing.** A redundant phrase that uses different wording survives. Only normalizations explicitly mapped in `context.user_normalizations` are merged.

- **No tense/voice normalization.** "Sent the email" and "the email was sent" are treated as different. Domain-specific detectors can be added.

---

## Known limitations

### v0.1.0

- **Sentence boundary detection is simplistic.** Uses `[.!?]\s+` regex; doesn't handle abbreviations ("e.g.", "Dr.") perfectly. False sentence-splits may cause false-duplicate misses.

- **Normalization key conflicts not detected.** If two normalization rules apply to overlapping spans, the longer key wins (sorted by length). Two equally-long conflicting keys produce undefined ordering.

- **No multi-word contradiction predicates.** `contradiction_predicates=[("send urgently", "do not send")]` works as literal-string matching but the multi-word match must appear contiguously. Rephrasings that paraphrase the predicate are missed.

- **Empty-kept-text duplicates rely on input_hash for integrity.** When `kept_text` is empty (full duplicate removal), `unbalance` verifies via the final `input_hash` round-trip. Trace tampering that preserves the hash but changes other fields will not be caught. Mitigation: traces should be stored alongside input hashes.

- **No locale handling.** Sentence-splitting and normalization rules are anglocentric in their default behavior. Domain users supply their own normalization tables.

---

## Errors discovered post-release

*(empty — first release)*

---

## How to report

If `muqabalah` produces an output you consider incorrect, or fails to flag a contradiction:

1. Open a GitHub issue with the exact prompt, context, and the unwanted output (or expected conflict).
2. Mark `bug:wrong-balance` or `bug:missed-conflict`.

Most fixes are detector-level: tighter regex, longer-key preference, or a new detector.
