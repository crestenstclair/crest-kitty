# Prior Art — Adversarial & Multi-Agent Code Review

Research underpinning this skill's design (surveyed 2026-08). The eight recurring patterns, then the systems they come from.

## The eight patterns

1. **Finder/skeptic split with a kill mandate.** Every serious system separates finders from a verifier whose job is to *refute*, not confirm. A "double-check" prompt rubber-stamps; a "kill this finding" prompt filters. (Refute-or-Promote, Cursor BugBot's validator, CodeRabbit's judge, Claude Code's verification step, CORE's ranker.)
2. **Evidence attached at generation time.** Findings carry file:line + quoted code + a concrete failure scenario; verification means re-opening that evidence. Claims without checkable evidence are dropped, not debated. (Ellipsis's hallucination filter, CodeRabbit reopening cited paths.)
3. **Execution beats argument.** Run cheap deterministic checks (grep, build, tests) before and during verification; a command output ends debates that prompting cannot. (Refute-or-Promote's headline lesson, MetaGPT's executable feedback.)
4. **Independence before consensus.** Reviewers work blind first; agreement across independent passes is the strongest true-positive signal. (BugBot v1's 8 shuffled-diff passes + majority vote, PoLL's disjoint-family juries, agent-review-panel's blind scoring.)
5. **Layered false-positive filtering.** Cheap category denylists → numeric confidence threshold → grounding judge. (Anthropic's security-review action drops findings below 8/10 confidence.)
6. **Severity gating + abstention.** Tag every survivor, cap low-severity volume, and make "no findings" a legitimate output. GitHub Copilot review stays silent on 29% of PRs by design.
7. **False positives cost more than false negatives.** Cursor's explicit economics: one FP erodes more trust than one FN. Optimize precision first.
8. **Guard the judge too.** Arbiters hallucinate; re-verify high-severity claims the judge itself introduces. (agent-review-panel's post-judge gate, CodeAgent's QA-Checker.)

## Research

| System | Contribution used here | Source |
|--------|------------------------|--------|
| **CriticGPT** (OpenAI 2024) | Dedicated critic role; identifies nitpicks/hallucinated bugs as the dominant critic failure mode; precision as a first-class dial | [arxiv.org/abs/2407.00215](https://arxiv.org/abs/2407.00215) |
| **CodeAgent** (EMNLP 2024) | Multi-role review team + QA-Checker supervisory agent against topic drift | [arxiv.org/abs/2402.02172](https://arxiv.org/abs/2402.02172) |
| **CORE** (Microsoft, FSE 2024) | Proposer/ranker duo; ranker cut false positives 25.8% | [arxiv.org/abs/2309.12938](https://arxiv.org/abs/2309.12938) |
| **Refute-or-Promote** (2026) | Kill mandate; findings need file:line + failure scenario; its worst FP died to a single empirical test, not better argument | [arxiv.org/pdf/2604.19049](https://arxiv.org/pdf/2604.19049) |
| **MetaGPT** (ICLR 2024) | Structured artifact handoffs; executable feedback over debate | [arxiv.org/abs/2308.00352](https://arxiv.org/abs/2308.00352) |
| **ChatDev** (ACL 2024) | Reviewer↔programmer dual-agent loops; communicative dehallucination | [arxiv.org/abs/2307.07924](https://arxiv.org/abs/2307.07924) |
| **AutoGen reflection** (Microsoft) | Generator+critic as a structural guarantee (nested chat), reviewer decomposition by issue class | [microsoft.github.io/autogen](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/design-patterns/reflection.html) |
| **PoLL / LLM juries** (Cohere 2024) | Panel of diverse judges beats one large judge; intra-model bias | [arxiv.org/abs/2404.18796](https://arxiv.org/abs/2404.18796) |
| **AI Safety via Debate** (2018) | Theoretical grounding for refute-to-verify amplification | [arxiv.org/abs/1805.00899](https://arxiv.org/abs/1805.00899) |

## Products

| System | Contribution used here | Source |
|--------|------------------------|--------|
| **CodeRabbit** | Judge model drops findings it cannot ground in re-opened code paths | [coderabbit.ai blog](https://www.coderabbit.ai/blog/how-coderabbit-delivers-accurate-ai-code-reviews-on-massive-codebases) |
| **Greptile** | Per-comment confidence exposed; acceptance rate as north-star metric | [greptile.com](https://www.greptile.com) |
| **Ellipsis** | Parallel generators → dedup → confidence filter → evidence-validating hallucination filter; refuted findings shown transparently | [zenml.io LLMOps database](https://www.zenml.io/llmops-database/building-and-deploying-production-llm-code-review-agents-architecture-and-best-practices) |
| **Qodo PR-Agent** | Token-aware diff compression; importance scores as the cheap-tier noise control | [github.com/qodo-ai/pr-agent](https://github.com/qodo-ai/pr-agent) |
| **GitHub Copilot code review** | Abstention as a feature; severity labels; comment grouping | [github.blog](https://github.blog/ai-and-ml/github-copilot/60-million-copilot-code-reviews-and-counting/) |
| **Anthropic claude-code-security-review** | Two-stage FP filter: category denylist + confidence < 8/10 dropped | [github.com/anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review) |
| **Cursor BugBot** | v1: 8 shuffled passes + majority vote + validator; explicit FP-cost economics; resolution-rate metric | [cursor.com/blog/building-bugbot](https://cursor.com/blog/building-bugbot) |
| **Claude Code /code-review** | Parallel specialized agents → verification against actual behavior → dedup → severity ranking | [code.claude.com/docs](https://code.claude.com/docs/en/code-review) |

## Agent-config prior art

| System | Contribution used here | Source |
|--------|------------------------|--------|
| **matsengrp/claude-code-agents** | Agent file format (name/description/model/color frontmatter, persona + detector-catalog body); tone spectrum across clean-code-reviewer / antipattern-scanner / code-smell-detector; successor repo's `surprising-conclusion-skeptic` | [github.com/matsengrp/claude-code-agents](https://github.com/matsengrp/claude-code-agents) (archived → [matsen/bipartite](https://github.com/matsen/bipartite) `agents/`) |
| **Adversarial Code Review action** | Optimizer/Skeptic waves; mechanical checks first; refutation backed by command output | [github marketplace](https://github.com/marketplace/actions/adversarial-code-review) |
| **wan-huiyan/agent-review-panel** | Blind scoring, anti-groupthink machinery, post-judge verification gate, epistemic tags | [github.com/wan-huiyan/agent-review-panel](https://github.com/wan-huiyan/agent-review-panel) |
| **todd866/codex-adversary** | Cross-vendor skeptic to break shared blind spots | [github.com/todd866/codex-adversary](https://github.com/todd866/codex-adversary) |
| **EveryInc compound-engineering `ce-code-review`** | Parallel persona reviewers merged into one deduped report; P0–P3 with action routing | [github.com/EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin/blob/main/docs/skills/ce-code-review.md) |

## Deliberately not adopted

- **Debate rounds between reviewers** (agent-review-panel): high token cost; evidence re-verification catches most of what debate would, without groupthink risk.
- **Cross-vendor models** (codex-adversary, crucible): out of scope for a single-vendor skill; role separation + blind independence recovers much of the diversity benefit.
- **Persistent learnings store** (CodeRabbit, BugBot rules): worth adding later; requires a feedback loop this skill doesn't yet have.
