# Algo-Trade Spec Package — Handoff for Claude Code

Specification-only package. No implementation code — Claude Code builds the system from these specs.

## How to use
1. Copy the entire contents of this folder to the root of a fresh git repo (including `.claude/` and `CLAUDE.md`).
2. Open Claude Code in that repo and start with:
   > Read CLAUDE.md and all files under specs/. Then execute Phase "P0 skeleton" from specs/00-overview.md,
   > following the engineering loop in specs/09-engineering-loop.md.
3. Claude Code delegates to the subagents in `.claude/agents/` per the delegation map in specs/09,
   or you can target one directly, e.g.:
   > @risk-engineer implement MaxDrawdownRule per specs/05-risk-agent.md

## Contents
```
CLAUDE.md                  project instructions, stack, design rules, DoD, safety rails
specs/
  00-overview.md           goals, non-goals, phases, success metrics
  01-architecture.md       layers, Protocols, DTOs, errors, config, composition root
  02..07-*.md              one spec per agent (data/strategy/backtest/risk/execution/monitoring)
  08-orchestrator.md       lifecycle + promotion gates
  09-engineering-loop.md   how Claude Code works: TDD loop, delegation, escalation, CI gates
.claude/agents/            7 subagents: architect, data-engineer, quant-researcher,
                           backtest-engineer, risk-engineer, execution-engineer, qa-reviewer
```

## Before starting (answer these, they shape config defaults)
- Target market/universe (TH equities? crypto? US?) → data vendor + broker adapter choice (P2)
- Initial risk limits (max position %, gross exposure, daily loss %, max DD)
- Historical data source location/format for the parquet feed

## Note
This system is a research/engineering tool and not financial advice. Live deployment is gated
(see specs/08) and remains the operator's decision and responsibility.
