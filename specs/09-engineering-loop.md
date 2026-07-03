# 09 — Engineering Loop (how Claude Code executes this project)

## Task source
Work through specs in order: 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08.
Within a spec, each unchecked acceptance criterion is one task. Track progress by checking boxes
in the spec file itself (edit the `[ ]` → `[x]`) in the same commit as the implementation.

## The loop (repeat per task)
1. **Plan** — restate the criterion, list files to touch, name the Protocols/DTOs involved.
   If the spec is ambiguous, write the ambiguity + your chosen resolution into `specs/DECISIONS.md` (ADR-lite: context, decision, why) and proceed.
2. **Red** — write the failing unit test first (`tests/unit/...` mirroring src path). Mock every I/O boundary with `pytest-mock`; assertions must state intent clearly.
3. **Green** — implement the minimum to pass. Respect design rules in `CLAUDE.md` (constructor injection, DTO mapping at edges, error mapping).
4. **Verify** — `uv run pytest -q && uv run ruff check . && uv run mypy src/`. All clean or loop back.
5. **Review** — invoke the `qa-reviewer` subagent on the diff. Address every finding marked MUST; log WONT-FIX rationale in the PR/commit body for SHOULDs you skip.
6. **Refactor** — only with green tests. No behavior change in refactor commits.
7. **Commit** — conventional commits: `feat(risk): max drawdown rule trips kill switch (spec 05)`.
   One criterion per commit. Include spec reference.

## Delegation map (subagents in `.claude/agents/`)
| Path | Subagent |
|---|---|
| domain/, interfaces/, orchestrator/wiring | `architect` |
| data/ | `data-engineer` |
| strategy/, research triage | `quant-researcher` |
| backtest/ | `backtest-engineer` |
| risk/ | `risk-engineer` |
| execution/, monitoring/ | `execution-engineer` |
| every diff before commit | `qa-reviewer` |

Main thread acts as tech lead: sequences tasks, resolves cross-module contract questions, owns `specs/DECISIONS.md`.

## Escalation / stop conditions (ask the human)
- A spec conflict that changes a Protocol signature already implemented elsewhere.
- Any temptation to weaken a risk rule, gate threshold, or safety rail.
- Adding a dependency not listed in the stack.
- Anything requiring real broker credentials or live trading.

## Quality gates for the whole repo (CI)
- `pytest` (unit) — required; integration marked and excluded from the fast gate
- `ruff check` + `ruff format --check`
- `mypy --strict src/`
- Architecture test (import isolation) — treated as a test failure, not a warning
- Coverage floor: 85% overall; 90% on `risk/` and `execution/`

## Definition of Done
See `CLAUDE.md`. A spec file is done when every checkbox is `[x]` and CI is green.
