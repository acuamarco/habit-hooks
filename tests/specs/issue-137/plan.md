# Implementation Plan: Portable Executable Documentation (#137)

## Overview

Replace the executable-spec harness's implicit `bash -c "set -o pipefail; …"`
executor with a small native Python command interpreter so the same Markdown
specs run on Windows, Linux, and macOS. Keep the existing Markdown context model,
markers, assertions, temp directories, and output normalization. Remove
`STEPS_RUN_ON_THIS_PLATFORM` / `POSIX_SHELL_ONLY` only after every command block
in the corpus is classified and either portable, tagged, intrinsically handled,
or explicitly `🟡`-skipped.

Product spec: `tests/specs/issue-137/issue.md`  
Technical spec: `tests/specs/issue-137/tech-spec.md`

## Architecture Decisions

- **Purpose-built lexer/parser**, not `shlex` — one grammar for quotes, operators,
  redirections, and Windows backslashes.
- **Immutable AST** (`command_model`) — interpret structure, then spawn; never
  spawn while still tokenizing.
- **Direct `Popen` with `shell=False`** — never discover Bash/WSL/Git Bash/
  PowerShell/`cmd.exe` as an implicit executor.
- **Capture via temp files** — avoid parent-pipe deadlocks on large stdout/stderr;
  enable stable descriptor duplication.
- **Left-to-right descriptor maps** — `2>&1 >file` ≠ `>file 2>&1`.
- **Rightmost-nonzero pipefail** — preserve current Bash effective behavior.
- **Reserved `$PATHSEP` and `$PYTHON`** — portable PATH construction and fixture
  processes without assuming `python` or `:` on PATH.
- **One `ln -s SOURCE LINK` intrinsic** — no general shell-utility emulation.
- **Refuse `.cmd`/`.bat`/`.ps1`** unless the document names their interpreter.
- **Missing executable → `SpecError`**, never synthetic exit 127.
- **200-line file limit** — new concerns live in dedicated modules; dependency
  direction:

```text
steps → command_runtime → command_process → command_model
                       → command_links   → command_model
command_parser → command_lexer → command_model
runner → steps
parser → markdown + steps
```

- **Platform seam** — import `habit_hooks.host_platform` and call
  `is_windows()` at apply time so `tests/platform_probe.py` can pin either
  branch.
- **No hidden Bash fallback** during migration — unparseable/unrunnable blocks
  must be migrated, tagged, or explicitly skipped.

## Dependency Graph

```text
command_model
    ├── command_lexer
    │       └── command_parser
    │               └── inventory audit (corpus classification)
    └── command_process / command_links
            └── command_runtime
                    └── steps.Context.run  (switch from bash)
                            ├── platform tags + no-command refusal
                            ├── harness unit-test fixture rewrite
                            ├── document migration (by category)
                            ├── remove global Windows gate
                            └── Bash-sentinel integration guard
```

Source metadata (`SourceSpan` on `Block`, `parse_spec(..., source=)`) and
platform-tag parsing can land early and feed diagnostics for the inventory and
runtime, but the inventory audit itself needs a working lexer/parser first.

## Task List

### Phase 1: Language foundation + discovery

- [ ] Task 1: Command model (`command_model.py`)
- [ ] Task 2: Lexer (`command_lexer.py` + focused tests)
- [ ] Task 3: Parser (`command_parser.py` + rejection matrix)
- [ ] Task 4: Migration inventory audit over all `*.spec.md` command blocks
- [ ] Task 5: Cross-platform runtime spike (direct / pipe / redirect / PATH / missing)

### Checkpoint: Foundation

- [ ] Inventory category counts sum to discovered corpus total; “unsupported and
      unclassified” drives migration work
- [ ] Spike proves no Bash resolution on pinned Windows and pinned POSIX
- [ ] `uv run pytest tests/test_spec_command_language.py` green

### Phase 2: Harness wiring (source, platform, env)

- [ ] Task 6: Source spans on `Block` + `parse_spec` source + `SpecError` locations
- [ ] Task 7: Platform tags, selection semantics, no-selected-command refusal
- [ ] Task 8: Case-correct env overlay + `$PATHSEP`/`$PYTHON`/`$PWD` in `SetEnv` and expansion

### Checkpoint: Selection

- [ ] `uv run pytest tests/test_spec_command_platform.py` green on pinned platforms
- [ ] Nonmatching tagged command preserves stdin / `last` / `exit_checked`

### Phase 3: Runtime (vertical capability slices)

- [ ] Task 9: Direct single-process execution (`command_process` + `command_runtime.run`)
- [ ] Task 10: Ordered redirections and FD duplication
- [ ] Task 11: Multi-stage pipelines + pipefail + cleanup
- [ ] Task 12: `&&`, `;`, newline sequencing with aggregate capture files
- [ ] Task 13: Command-prefix assignments
- [ ] Task 14: `ln -s` intrinsic (`command_links.py`)

### Checkpoint: Runtime complete

- [ ] `uv run pytest tests/test_spec_command_runtime.py tests/test_spec_command_links.py` green
- [ ] No Bash spawn in any runtime test path

### Phase 4: Switch harness + docs

- [ ] Task 15: Switch `Context.run` to native runtime; track `commands_run`
- [ ] Task 16: Rewrite `test_spec_markers` / `test_spec_contexts` fixtures to `$PYTHON`
- [ ] Task 17: Update `docs/executable_spec.md` (tags, subset, paired example)

### Checkpoint: Ready to migrate documents

- [ ] Existing harness unit tests pass on Windows without the global gate
  (gate may still exist until Task 23 — fixtures must be ready first)
- [ ] Authoring doc matches the product contract

### Phase 5: Corpus migration + gate removal

- [ ] Task 18: Migrate native-compatible / mechanical-rewrite blocks
- [ ] Task 19: Environment preambles → `$PATHSEP`
- [ ] Task 20: POSIX utility fixtures → `$PYTHON -c …`
- [ ] Task 21: Platform path pairs (`/dev/null`↔`NUL`, venv bins, etc.)
- [ ] Task 22: Confirm `ln -s` blocks via intrinsic; mark product-level POSIX
      sensor-recipe cases `🟡` with tracked reasons
- [ ] Task 23: Remove global platform gate and exports (inventory clean)
- [ ] Task 24: Bash-sentinel integration guard
- [ ] Task 25: Release evidence (pass/skip counts, remaining `🟡`, no Bash)

### Checkpoint: Complete

- [ ] `STEPS_RUN_ON_THIS_PLATFORM`, `POSIX_SHELL_ONLY`, and `["bash", "-c", …]`
      have no remaining harness references
- [ ] Windows skips ≥115 fewer executable-doc cases than #137 baseline
- [ ] `uv run pytest` green on Linux/macOS; Windows CI green with only explicit skips
- [ ] Ready for human review / PR

## Parallelization Opportunities

| Parallelizable | Sequential |
|---|---|
| Tasks 6–7 after Task 3 (source/platform while spike proceeds) | Tasks 1→2→3 |
| Tasks 18–21 after Task 15 (different docs / categories) with care | Tasks 9→10→11→12 (runtime layers) |
| Task 14 (links) after Task 9 (needs expansion, not pipelines) | Task 23 after inventory empty |
| Task 17 (docs) anytime after Task 7 | Task 24 after gate removal |

Prefer one agent for runtime (Tasks 9–14) and another for inventory-driven
migration prep once the parser exists — but only one agent should edit a given
`*.spec.md` at a time. Use separate git worktrees if both will run pytest
(shared `.spec-runs/` and wheelhouse).

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Corpus contains syntax outside the closed language | High — blocks gate removal | Inventory audit before runtime investment; migrate or `🟡`; broaden language only via explicit spec revision |
| Windows symlink privilege (error 1314) | Med — link fixtures fail | Intrinsic + actionable `SpecError`; real-link tests gated by `A_MACHINE_THAT_CAN_MAKE_A_SYMLINK`; inject fake linker for logic |
| Pipe deadlock / partial pipeline on missing exe | High — flakes or false greens | Resolve entire pipeline before spawn; temp-file capture; cleanup terminate→kill→reap |
| Case-insensitive env duplicates on Windows (`PATH`/`Path`) | High — wrong child PATH | Single overlay helper for SetEnv, prefixes, reserved vars, resolution, and `Popen` env |
| Accidental Bash fallback during migration | High — defeats #137 | No fallback path; sentinel integration test; inventory must be clean before gate removal |
| Concurrent pytest in one checkout | Med — false reds | Worktrees per agent; treat packaging/spec flakes as non-evidence until quiet re-run |
| Product `command = "…"` sensor recipes still POSIX-only | Low for this work | Explicit leaf `🟡` only; out of scope per product non-goals |

## Open Questions

- None blocking start: the technical spec is the contract. If the inventory
  discovers a new syntax family, stop and revise the technical spec + test
  matrix before broadening the language.
- Confirm with human before removing the global gate (Task 23) that the
  inventory attachment on the PR has an empty “unsupported and unclassified”
  bucket and that every remaining skip has a tracked issue.

## Verification Commands (repo conventions)

- Focused: `uv run pytest tests/test_spec_command_language.py` (and sibling modules)
- Harness units: `uv run pytest tests/test_spec_markers.py tests/test_spec_contexts.py tests/spec_runs.py`
- Lint: `uv run ruff check` on edited paths (and IDE diagnostics)
- Full: `uv run pytest` in a quiet checkout
- Completion grep: no `STEPS_RUN_ON_THIS_PLATFORM`, `POSIX_SHELL_ONLY`, or
  harness `["bash", "-c"` remaining under `tests/harness/`, `conftest.py`,
  `tests/spec_runs.py`
