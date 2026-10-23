---
name: writing-clean-code
description: Use when writing new code, adding classes, creating features, or structuring implementations - guides SOLID principles, clean code, dependency injection, and design pattern selection
---

# Writing Clean Code

## Overview

Guide for writing code that is obvious to other programmers, contains no duplication, has minimal complexity, and is testable. Applies SOLID principles, clean code practices, and design patterns as a default writing discipline — not as an afterthought.

## When to Use

- Writing new classes, methods, or features
- Structuring a new module or subsystem
- Deciding how objects should relate to each other
- Choosing between inheritance, composition, or delegation

**When NOT to use:** Reviewing existing code (use `adversarial-review` instead — its hunter agents cover the smell catalog and its clean-code-reviewer agent covers SOLID).

## The Five Qualities of Clean Code

1. **Obvious to other programmers** — clear naming, no magic numbers, no hidden side effects
2. **No duplication** — one change, one place
3. **Minimal moving parts** — fewest classes and methods that solve the problem
4. **Passes all tests** — if it isn't tested, it isn't done
5. **Cheap to maintain** — consequence of the above four

## Core Discipline

The one-line versions. Full explanations and code examples live in the references below.

| Principle | One-liner | Reference |
|-----------|-----------|-----------|
| **SRP** | One reason to change per class — describable without "and" | [solid.md](references/solid.md) |
| **OCP** | New type = new class, not an edited switch | [solid.md](references/solid.md) |
| **LSP** | Any implementation swaps in without the caller knowing | [solid.md](references/solid.md) |
| **ISP** | No client depends on methods it doesn't use | [solid.md](references/solid.md) |
| **DIP** | Depend on abstractions; interface anything touching framework/I/O | [solid.md](references/solid.md) |
| **DI** | Classes never `new` their own dependencies | [dependency-injection.md](references/dependency-injection.md) |
| **Naming/functions/comments** | Reveal intent; do one thing; comment only what code can't say | [clean-code-rules.md](references/clean-code-rules.md) |
| **Patterns** | Solve present problems, not imagined ones | [design-patterns.md](references/design-patterns.md) |

## References

- [references/solid.md](references/solid.md) — all five principles with WRONG/RIGHT code examples, plus when to create an interface
- [references/dependency-injection.md](references/dependency-injection.md) — the constructor-injection pattern, redundant coupling, constructor rules
- [references/clean-code-rules.md](references/clean-code-rules.md) — naming, functions, comments, error handling, boundaries, common mistakes
- [references/design-patterns.md](references/design-patterns.md) — pattern selection tables and the inheritance-vs-composition flowchart

Read the reference that matches the decision at hand; don't load all four for a one-method change.

## Quick Self-Check Before Finishing

1. Can every new class be described without "and"?
2. Does any class `new` a dependency it should receive?
3. Would adding the next obvious variant require editing existing code?
4. Is there a magic number, a lying name, or a comment restating code?
5. Three similar lines are fine; a premature abstraction is not — did you wait for the Rule of Three?
