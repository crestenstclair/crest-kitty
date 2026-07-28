---
name: spk-gate-accept
description: "Run the Spec Kitty accept gate for a completed mission and verify final readiness before merge."
---

# spk-gate-accept

Use this skill when runtime reaches terminal state, the user asks to accept a
mission, or all WPs appear complete.

## Flow

1. Run `/spec-kitty.accept` or the equivalent CLI command.
2. Confirm all required WPs are approved or done.
3. Verify required tests, artifacts, and mission invariants.
4. When the project declares an architecture spec (`.kittify/architecture`),
   accept also runs **deterministic acceptance**: every declared project check
   and applicable attached validation executes, and the versioned report is
   recorded to `<mission>/deterministic-acceptance.json`. Both layers must
   pass — deterministic gates AND the adversarial semantic review embedded in
   the accept prompt (obligation ledger, evidence-complete findings, the nine
   architecture-drift guards). A green command with zero executed tests, or a
   success marker from a still-resident process, is a failure, not a pass.
5. If accept fails, route to `spk-run-blocked-recovery`.
6. If accept passes, route to `spk-gate-merge`.

## Rule

Accept is not a formality. It is the final pre-merge readiness gate, and it is
the ONLY lifecycle step that executes declared acceptance validations —
ordinary reads (context, doctor, lint, archive) never do.
