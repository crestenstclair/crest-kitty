---
name: spk-gate-archive
description: "Archive a terminal mission after operator approval, consuming recorded acceptance without re-running anything."
---

# spk-gate-archive

Use this skill when an operator asks to archive a terminal (merged or
canceled) mission.

## Flow

1. Confirm the operator identity (`--by`) and a stated reason — archiving is
   never automatic (AM-4) and never anonymous.
2. Run `spec-kitty archive create --mission <handle> --by <operator> --reason "<why>"`.
3. If refused, report the guard code verbatim (AM-1 terminal-only, AM-2
   still-present invariant, AM-6 missing/failed recorded deterministic
   acceptance) and route the underlying problem back to the appropriate step —
   a refusal is fixed by resolving the state, not by retrying the archive.

## Rule

Archive consumes reviewed completion state and operator approval. It must NOT
re-run acceptance, start validations, runtime sessions, supervisors, or
interaction drivers, and it must not embed or repeat the execution-acceptance
contract — that work belongs to accept/review, and a recorded passing
deterministic report is a precondition (AM-6), not something archive
regenerates. Archiving is an ordinary read plus one append to the immutable
registry.
