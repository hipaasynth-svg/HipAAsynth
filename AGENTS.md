# HipAAsynth — project guide for coding agents

HipAAsynth generates deterministic synthetic patients and runs 7AAST, a stress
test of clinical AI models. Start with [README.md](README.md),
[docs/7AAST.md](docs/7AAST.md) and [docs/HISTORY.md](docs/HISTORY.md) (core vs
extras).

## Where things are

| Path | What |
|---|---|
| `hipaasynth/aast/` | 7AAST: `adapter.py` (model output types), `stats.py` (intervals, verdicts, noise floor), `cases.py` (what the model sees), `run.py` (`run_7aast`), `files.py` (test by file), `report.py` (hash chain, HTML, `verify`), `cli.py`, `web.py` (`POST /7aast`) |
| `hipaasynth/decision_cohort.py` | True cases mixed with clinical look-alikes; pulse-oximeter reading |
| `hipaasynth/polymorphic/` | Seven written forms; `blinding.py` decides what is hidden at decision time |
| `hipaasynth/dif/`, `psf/`, `cc/`, `adversarial/` | The older per-axis engines 7AAST builds on |
| `hipaasynth/api.py`, `run/main.py`, `sdk.py`, `ui/` | Front doors: REST API + pages, CLI (`hipaasynth`, `hipaasynth 7aast`, `hipaasynth ui`), SDK |

## Rules that keep results trustworthy

- **Determinism.** Same seed, same output, across processes. Use
  `core.hashing.stable_seed_from_id`, never `hash()`. When you change engine
  code, prove old (non-blinded) forms and outputs are byte-identical.
- **No answer leaks.** Anything a blinded case shows must be knowable at the
  decision moment and must not separate true cases from look-alikes on its own;
  `tests/test_decision_realism.py` enforces this. New observation fields that
  are treatment, outcomes or generator bookkeeping go in `polymorphic/blinding.py`.
- **Wording.** Never call a report a certification, and never call the product
  a synthetic data vendor. Demo models are always labelled DEMO.
- **Pure standard library** in the engine. No PHI, ever.
- **Checks before a PR:** `python -m pytest`, `ruff check` and `ruff format` on
  changed files, `mypy hipaasynth/aast`.

## Code intelligence

The GitNexus block below is generated. Its index command is out of date: build
the index with `npx -y gitnexus analyze --index-only` (the flag keeps it from
rewriting this file), then use `npx -y gitnexus impact <symbol> --direction
upstream --repo .` and `npx -y gitnexus detect-changes --scope staged --repo .`.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **HipAAsynth** (2491 symbols, 4685 relationships, 173 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/HipAAsynth/context` | Codebase overview, check index freshness |
| `gitnexus://repo/HipAAsynth/clusters` | All functional areas |
| `gitnexus://repo/HipAAsynth/processes` | All execution flows |
| `gitnexus://repo/HipAAsynth/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->