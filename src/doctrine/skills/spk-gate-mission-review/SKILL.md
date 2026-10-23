---
name: spk-gate-mission-review
description: "Run post-merge Spec Kitty mission review for spec-to-code fidelity, FR coverage, drift, risk, and final verdict."
---

# spk-gate-mission-review

Use this skill after a mission has merged or when the user asks for a mission
review.

## Flow

1. Compare spec, plan, tasks, WPs, reviews, and merged code.
2. Trace functional requirements to implementation evidence.
3. Identify drift, missing tests, security concerns, and follow-up issues.
4. Run the `adversarial-review` skill over the mission diff for structural
   quality (six blind hunters, then a skeptic with a kill mandate). Mandatory,
   and not substitutable with an improvised smell hunt.
5. Produce a final verdict and record follow-ups.

Structural smells are maintainability signals: they are reported, but a smell
alone never forces a FAIL verdict.

## Legacy Alias

For detailed review mechanics, use `spec-kitty-mission-review` when available.
