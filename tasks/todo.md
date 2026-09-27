# Tasks: Portable Executable Documentation (#137)

See `tasks/plan.md` for architecture, risks, and phase overview.

Focused verification pattern: `uv run pytest <listed tests>` then
`uv run ruff check <touched files>`.

---

## Task 1: Command model

**Description:** Add frozen enums/dataclasses for source spans, words, redirections,
commands, pipelines, `&&` chains, and scripts. No I/O or subprocess.

**Acceptance criteria:**
- [ ] `tests/harness/command_model.py` exists with `SourceSpan`, `CommandPlatform`,
      `Word`/`Literal`/`Variable`, `Assignment`, `Redirection`, `SimpleCommand`,
      `Pipeline`, `AndChain`, `Script` as frozen types matching the technical spec
- [ ] Module imports neither subprocess, pytest, nor product sensor modules
- [ ] File stays under the 200-line gate

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_language.py -q` (may be empty/skip until Task 2)
- [ ] Build succeeds: `uv run ruff check tests/harness/command_model.py`
- [ ] Manual check: types import cleanly from a REPL / unit import

**Dependencies:** None

**Files likely touched:**
- `tests/harness/command_model.py` (new)

**Estimated scope:** Small (1–2 files)

---

## Task 2: Command lexer

**Description:** Character-by-character lexer for the closed command language:
words/quotes/variables, operators, FD_DUP longest-match, source offsets, and
rejection of unsupported shell syntax at the token level where appropriate.

**Acceptance criteria:**
- [ ] `tests/harness/command_lexer.py` emits the token set in the technical spec
- [ ] Backslash rules match the narrowed Bash subset (Windows paths preserved)
- [ ] Separated/unsupported FD forms (`2> &1`, `0>&1`, …) error rather than split
- [ ] Unit tests cover quoting, adjacent parts, empty quoted args, `$NAME`/
      `${NAME}`, single-quoted jq literals, Windows backslashes, multiline quotes

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_language.py -q -k lexer`
- [ ] Build succeeds: `uv run ruff check tests/harness/command_lexer.py tests/test_spec_command_language.py`
- [ ] Manual check: a known jq-heavy word tokenizes as one WORD

**Dependencies:** Task 1

**Files likely touched:**
- `tests/harness/command_lexer.py` (new)
- `tests/test_spec_command_language.py` (new)

**Estimated scope:** Medium (3–5 files)

---

## Task 3: Command parser + rejection matrix

**Description:** Recursive-descent parser from tokens to `command_model`, with
operator precedence, command-prefix assignment recognition, and SpecErrors for
every unsupported construct listed in the technical spec.

**Acceptance criteria:**
- [ ] `tests/harness/command_parser.py` implements the published grammar
- [ ] Precedence: `a | b && c ; d` → pipe, then conditional, then unconditional
- [ ] Empty commands / `;;` / unsupported ops (`||`, bare `&`, backticks, globs,
      heredocs, `!`, keywords, …) raise `SpecError`
- [ ] Parser tests assert ASTs and spawn nothing
- [ ] All rejection cases from the technical “Unsupported syntax” section have tests

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_language.py -q`
- [ ] Build succeeds: `uv run ruff check tests/harness/command_parser.py`
- [ ] Manual check: module does not import subprocess

**Dependencies:** Task 2

**Files likely touched:**
- `tests/harness/command_parser.py` (new)
- `tests/test_spec_command_language.py`

**Estimated scope:** Medium (3–5 files)

---

## Task 4: Migration inventory audit

**Description:** Run the lexer/parser over every command fence in the 14
executable documents. Classify each block exactly once; attach the inventory to
the implementing PR. Collect all parser errors rather than stopping at the first.

**Acceptance criteria:**
- [ ] Inventory lists source path + line for every command block
- [ ] Categories: portable as-is; portable after stated mechanical rewrite;
      posix/windows pair; `ln -s` intrinsic; explicit product-level POSIX skip;
      unsupported-and-unclassified
- [ ] Category counts sum to discovered corpus total (not the historical 206)
- [ ] Final category must be empty before Task 23; until then it is the backlog
- [ ] Audit script or one-shot command is reproducible from the PR description

**Verification:**
- [ ] Tests pass: N/A (audit artifact) — parser suite still green
- [ ] Manual check: re-run audit; totals reconcile; errors reported together

**Dependencies:** Task 3

**Files likely touched:**
- `tests/harness/` (read-only consume) or a short `tests/` audit helper if kept
- PR notes / inventory markdown attachment (not product docs)

**Estimated scope:** Medium (script + report; avoid XL doc edits here)

---

## Task 5: Cross-platform runtime spike

**Description:** Thin spike (not the full design) that executes representative
direct invocation, pipeline, ordered redirection, command-scoped PATH, and
missing-executable cases on pinned POSIX and pinned Windows without resolving Bash.

**Acceptance criteria:**
- [ ] Spike covers the five representative cases on both pinned platforms
- [ ] No argv names `bash` / a failing `bash.exe` sentinel
- [ ] Findings (if any new syntax family) feed Task 4 / open questions — do not
      silently broaden the language

**Verification:**
- [ ] Tests pass: focused spike test module or marked tests green
- [ ] Manual check: PATH has no required Bash for the spike to pass

**Dependencies:** Tasks 3 (parser); ideally Task 4 in progress for case selection

**Files likely touched:**
- Temporary or early `command_runtime` / `command_process` stubs
- Small spike test under `tests/`

**Estimated scope:** Medium (3–5 files) — keep disposable if it diverges from final shape

---

## Checkpoint: Foundation

- [ ] Inventory attached; category totals reconcile
- [ ] Spike proves Bash-free execution on both pinned branches
- [ ] `uv run pytest tests/test_spec_command_language.py` green
- [ ] Review with human before full runtime investment if inventory has surprises

---

## Task 6: Source metadata + SpecError locations

**Description:** Attach markdown-it fence start line as one-based `SourceSpan` on
`Block`; thread `source` through `parse_spec`; format command-language SpecErrors
with source, line, column, offending line, and caret. Update `SpecError` docstring.

**Acceptance criteria:**
- [ ] `Block` carries source location; `parse_spec(text, source="<inline>")`
- [ ] `SpecFile.collect` passes `str(self.path)`
- [ ] Lexer/parser offsets translate through the fence span
- [ ] `SpecError` docstring: “malformed or unrunnable spec”

**Verification:**
- [ ] Tests pass: focused tests asserting error location text
- [ ] Build succeeds: `uv run ruff check tests/harness/markdown.py tests/harness/parser.py tests/harness/errors.py conftest.py`
- [ ] Manual check: a bad fence names the `.spec.md` path and line

**Dependencies:** Task 1 (`SourceSpan`); can parallelize with Task 4 after Task 3

**Files likely touched:**
- `tests/harness/markdown.py`
- `tests/harness/parser.py`
- `tests/harness/errors.py`
- `conftest.py`

**Estimated scope:** Medium (3–5 files)

---

## Task 7: Platform tags + no-command refusal

**Description:** Parse `bash` / `bash posix` / `bash windows` into `Command` with
`CommandPlatform | None`. Apply-time selection via `host_platform.is_windows()`.
Nonmatching returns without side effects. Runner refuses `commands_run == 0`.

**Acceptance criteria:**
- [ ] Strict tag validation (case-sensitive; >2 tokens / unknown → SpecError at parse)
- [ ] Untagged runs everywhere; posix/windows filter correctly under `platform_probe`
- [ ] Adjacent alternatives share one following assertion
- [ ] Nonmatching preserves pending stdin, `last`, `exit_checked`, does not bump
      `commands_run`
- [ ] `runner.execute` raises SpecError when no command selected

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_platform.py -q`
- [ ] Build succeeds: `uv run ruff check tests/harness/parser.py tests/harness/steps.py tests/harness/runner.py`
- [ ] Manual check: pinning uses `platform_probe`, not `sys.platform`

**Dependencies:** Task 6 (source on Command helpful); Task 1 for `CommandPlatform`

**Files likely touched:**
- `tests/harness/parser.py`
- `tests/harness/steps.py`
- `tests/harness/runner.py`
- `tests/test_spec_command_platform.py` (new)

**Estimated scope:** Medium (3–5 files)

---

## Task 8: Environment overlay + reserved substitutions

**Description:** One overlay helper for SetEnv, command-prefix assignments,
reserved `PWD`/`PATHSEP`/`PYTHON`, executable resolution, and `Popen` env.
Windows case-insensitive collapse; reserved values applied after inherited env.

**Acceptance criteria:**
- [ ] `SetEnv.apply` safe_substitutes `PWD`, `PATHSEP`, `PYTHON`
- [ ] Windows: `$PATH`/`$Path`/`$path` read alike; update removes all spellings
      then stores the supplied spelling
- [ ] POSIX: `Path` and `PATH` remain distinct
- [ ] Helper used everywhere env is built for children

**Verification:**
- [ ] Tests pass: cases in `tests/test_spec_command_runtime.py` (env section) and/or platform tests
- [ ] Build succeeds: `uv run ruff check` on the helper module + `steps.py`
- [ ] Manual check: `PATH=value command` cannot leave inherited `Path` beside `PATH`

**Dependencies:** Task 7 useful but not hard-required; needed before Task 9

**Files likely touched:**
- `tests/harness/steps.py` (SetEnv)
- New small helper module under `tests/harness/` if size requires (e.g. part of runtime)

**Estimated scope:** Small–Medium (1–3 files)

---

## Checkpoint: Selection

- [ ] Platform tests green under both pins
- [ ] Source-located SpecErrors readable
- [ ] Env overlay behavior pinned for Windows and POSIX

---

## Task 9: Direct single-process execution

**Description:** Implement `command_runtime.run` + `command_process` for one
external executable: word expansion, PATH resolution (incl. empty segment =
case dir), Windows PATHEXT / refuse `.cmd`.bat`.ps1`, UTF-8 replace decode,
stdin delivery, missing executable → SpecError before spawn.

**Acceptance criteria:**
- [ ] `run(script, CommandContext, SourceSpan) -> CompletedProcess[str]` with
      `args` = original script
- [ ] `shell=False`; absolute resolved executable
- [ ] Portable fixtures use `sys.executable` / `$PYTHON -c`
- [ ] `.cmd`/`.bat` refusal message tells author to name `cmd.exe`/PowerShell in
      `bash windows`

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py -q -k "direct or path or missing or cmd"`
- [ ] Build succeeds: `uv run ruff check tests/harness/command_runtime.py tests/harness/command_process.py`
- [ ] Manual check: both modules stay under 200 lines

**Dependencies:** Tasks 3, 8

**Files likely touched:**
- `tests/harness/command_runtime.py` (new)
- `tests/harness/command_process.py` (new)
- `tests/test_spec_command_runtime.py` (new)

**Estimated scope:** Medium (3–5 files)

---

## Task 10: Ordered redirections

**Description:** Support the documented redirect set with left-to-right descriptor
maps; duplication copies current destination (not a live alias). Relative paths
against case dir. Open failures → SpecError before any stage starts. No
`/dev/null`→`NUL` translation.

**Acceptance criteria:**
- [ ] All operators in the technical Redirection section work
- [ ] Order difference between `2>&1 >file` and `>file 2>&1` is tested
- [ ] Redirections interleaved among argv are stripped and applied in source order

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py -q -k redirect`
- [ ] Build succeeds: ruff on runtime/process modules
- [ ] Manual check: open failure does not leave orphan processes

**Dependencies:** Task 9

**Files likely touched:**
- `tests/harness/command_process.py`
- `tests/harness/command_runtime.py`
- `tests/test_spec_command_runtime.py`

**Estimated scope:** Medium (3–5 files)

---

## Task 11: Pipelines + pipefail + cleanup

**Description:** Multi-stage pipelines: expand/resolve/open all stages before
spawn; inter-stage pipes; pipefail = rightmost nonzero; cleanup
terminate→kill→reap on failure; ignore BrokenPipeError on early consumer exit;
large I/O without deadlock.

**Acceptance criteria:**
- [ ] Missing later executable fails before any stage starts
- [ ] Early failing producer + successful consumer still yields nonzero pipefail
- [ ] Downstream early exit and large stdin/stdout/stderr covered by tests
- [ ] Cleanup promises only direct children (no process-tree claim)

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py -q -k "pipe or cleanup or deadlock"`
- [ ] Build succeeds: ruff on touched modules
- [ ] Manual check: no unread parent pipes for aggregate capture

**Dependencies:** Task 10

**Files likely touched:**
- `tests/harness/command_process.py`
- `tests/harness/command_runtime.py`
- `tests/test_spec_command_runtime.py`

**Estimated scope:** Medium (3–5 files)

---

## Task 12: Sequencing (`&&`, `;`, newlines)

**Description:** Evaluate `AndChain` short-circuit and unconditional sequence
continuation; one pair of aggregate stdout/stderr temp files per fence; script
result = last pipeline actually executed.

**Acceptance criteria:**
- [ ] `&&` stops chain on nonzero; `;`/newline continues
- [ ] Newline after `|`/`&&` is continuation whitespace
- [ ] Output aggregation across sequences is tested
- [ ] No default timeout added

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py -q -k "and_ or sequence or semi"`
- [ ] Build succeeds: ruff on runtime module
- [ ] Manual check: blank lines ignored; `;;` still SpecError from parser

**Dependencies:** Task 11

**Files likely touched:**
- `tests/harness/command_runtime.py`
- `tests/test_spec_command_runtime.py`

**Estimated scope:** Small–Medium (1–3 files)

---

## Task 13: Command-prefix assignments

**Description:** Temporary `NAME=value` before the command name affect only that
child’s environment; values expand against case env; one assignment does not
introduce a variable for another in the same prefix; assignment-only / `export`
/ post-name assignments already rejected by parser.

**Acceptance criteria:**
- [ ] Prefix env visible to child only for that command
- [ ] Uses the same overlay helper as Task 8
- [ ] Covered in runtime tests with `$PYTHON -c` inspecting env

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py -q -k assign`
- [ ] Build succeeds: ruff on touched files
- [ ] Manual check: persistent `✏️` values unchanged after prefixed command

**Dependencies:** Tasks 8, 9 (parser already recognizes assignments from Task 3)

**Files likely touched:**
- `tests/harness/command_runtime.py`
- `tests/test_spec_command_runtime.py`

**Estimated scope:** Small (1–2 files)

---

## Task 14: Symlink intrinsic

**Description:** Exact `ln -s SOURCE LINK` after expansion, before resolution.
Native `Path.symlink_to` with injectable filesystem for tests; relative source
preserved; Windows privilege failures → actionable SpecError.

**Acceptance criteria:**
- [ ] `tests/harness/command_links.py` implements the intrinsic only
- [ ] Invalid forms / pipeline participation refused
- [ ] Injected Windows privilege failure covered
- [ ] One real link test gated by `platform_probe.A_MACHINE_THAT_CAN_MAKE_A_SYMLINK`

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_links.py -q`
- [ ] Build succeeds: `uv run ruff check tests/harness/command_links.py`
- [ ] Manual check: no `ln` PATH search

**Dependencies:** Task 9 (expansion + dispatch hook); sequencing allowed

**Files likely touched:**
- `tests/harness/command_links.py` (new)
- `tests/harness/command_runtime.py`
- `tests/test_spec_command_links.py` (new)

**Estimated scope:** Medium (3–5 files)

---

## Checkpoint: Runtime complete

- [ ] Runtime + links test modules green
- [ ] Spike cases subsumed by real runtime tests
- [ ] Human review before switching `Context.run`

---

## Task 15: Switch `Context.run` to native runtime

**Description:** Delegate selected command text to `command_runtime.run`; implement
apply-time platform gating and `commands_run` accounting; clear stdin in `finally`
once execution attempted; lex/setup SpecErrors still count as attempted.

**Acceptance criteria:**
- [ ] No `["bash", "-c", …]` in `tests/harness/steps.py`
- [ ] Default exit check / `last` / `exit_checked` semantics preserved
- [ ] Global Windows skip constants still present until Task 23 (do not remove yet
      unless inventory already clean — prefer keep gate)

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_command_runtime.py tests/test_spec_command_platform.py tests/test_spec_command_links.py -q`
- [ ] Build succeeds: ruff on `steps.py` / `runner.py`
- [ ] Manual check: dependency direction matches the technical diagram

**Dependencies:** Tasks 7, 9–14

**Files likely touched:**
- `tests/harness/steps.py`
- `tests/harness/runner.py`

**Estimated scope:** Small–Medium (2–3 files)

---

## Task 16: Rewrite harness unit-test command fixtures

**Description:** Replace shell-utility fixtures in `test_spec_markers.py` and
`test_spec_contexts.py` with `$PYTHON` / `sys.executable -c` forms. Keep marker/
context meaning tests in those modules; language details stay in new modules.

**Acceptance criteria:**
- [ ] No reliance on `echo`/`true`/`false`/`cat`/etc. in those harness tests
- [ ] Once the gate is removed, every test in both modules can run on Windows

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_spec_markers.py tests/test_spec_contexts.py tests/spec_runs.py -q`
- [ ] Build succeeds: ruff on those test files
- [ ] Manual check: tests still assert marker/context meanings, not parser internals

**Dependencies:** Task 15

**Files likely touched:**
- `tests/test_spec_markers.py`
- `tests/test_spec_contexts.py`

**Estimated scope:** Medium (2 files, potentially many edits)

---

## Task 17: Update `docs/executable_spec.md`

**Description:** Document that `bash` labels a command block (not Bash invocation),
the portable subset, platform tags, and a paired posix/windows example with shared
assertions plus an untagged everywhere command. Must land before new syntax is
used widely in other docs (may precede bulk migration).

**Acceptance criteria:**
- [ ] Paired example shows: posix step, windows step, shared `🖥️`/`🚨`, untagged step
- [ ] States no implicit shell discovery
- [ ] Documents `$PATHSEP` / `$PYTHON` as needed for authors

**Verification:**
- [ ] Manual check: doc matches product acceptance criteria
- [ ] Spec suite still collects the file if it is/ becomes executable — or keep as
      pure authoring doc per current role

**Dependencies:** Task 7 (contract stable)

**Files likely touched:**
- `docs/executable_spec.md`

**Estimated scope:** Small (1 file)

---

## Checkpoint: Ready to migrate documents

- [ ] Native `Context.run` live
- [ ] Harness unit fixtures portable
- [ ] Authoring doc updated
- [ ] Inventory “unsupported and unclassified” is the migration backlog

---

## Task 18: Migrate native-compatible blocks

**Description:** First migration pass: direct `habit-*`, Git, jq, uv, and
plugin-owned executable invocations that need no change or only stated mechanical
rewrites. Keep assertions unchanged.

**Acceptance criteria:**
- [ ] Inventory items in “portable” / “mechanical rewrite” cleared or rewritten
- [ ] No assertion text changes that alter expected product outcomes by platform

**Verification:**
- [ ] Tests pass: focused `uv run pytest` on touched `*.spec.md` paths
- [ ] Re-run inventory; those categories shrink accordingly

**Dependencies:** Tasks 15, 17; Task 4 inventory

**Files likely touched:**
- Selected files under `docs/**/*.spec.md` and `plugins/*/docs/*.spec.md`

**Estimated scope:** Medium (spread across docs — split further by document if >5 files in one session)

---

## Task 19: Environment preambles → `$PATHSEP`

**Description:** Replace `$PWD/node_modules/.bin:$PATH` (and similar) with
`$PATHSEP` form in generic and TypeScript plugin preambles.

**Acceptance criteria:**
- [ ] No colon-joined PATH construction left in those preambles
- [ ] Same assertions; works when Windows gate eventually lifts

**Verification:**
- [ ] Tests pass: plugin spec modules for generic/typescript
- [ ] Manual check: inventory no longer flags those blocks for PATHSEP rewrite

**Dependencies:** Tasks 8, 15

**Files likely touched:**
- `plugins/generic/docs/generic-plugin.spec.md`
- `plugins/typescript/docs/typescript-plugin.spec.md`

**Estimated scope:** Small (1–2 files)

---

## Task 20: POSIX utility fixtures → `$PYTHON`

**Description:** Replace `cat`/`head`/`printf`/`sed`/`grep`/`seq` setup/scrub
commands with short `$PYTHON -c …` where equivalent. Keep a utility only when the
document intentionally teaches that utility (then tag or skip appropriately).

**Acceptance criteria:**
- [ ] Migrated fixtures are untagged portable commands
- [ ] Teaching-utility exceptions are explicitly classified in inventory

**Verification:**
- [ ] Tests pass: affected docs
- [ ] Re-run inventory; utility category reduced

**Dependencies:** Task 15

**Files likely touched:**
- Multiple `*.spec.md` (batch by inventory list; stop at ~5 files per session)

**Estimated scope:** Medium (split if XL)

---

## Task 21: Platform path pairs

**Description:** Add adjacent `bash posix` / `bash windows` steps for `/dev/null`↔
`NUL`, venv `bin`↔`Scripts`, POSIX-only PATH values, and differing executable
filenames. Shared expected output/stderr/exit/files.

**Acceptance criteria:**
- [ ] Shared assertions remain untagged
- [ ] Both alternatives produce the same externally visible effect
- [ ] No `/dev/null` left in untagged commands that must run on Windows

**Verification:**
- [ ] Tests pass on pinned platforms for affected cases
- [ ] Manual check: compare shared assertions for every tagged pair

**Dependencies:** Task 7, 15

**Files likely touched:**
- Inventory-selected `*.spec.md` files

**Estimated scope:** Medium (split by doc if needed)

---

## Task 22: Symlinks + product-level POSIX recipe skips

**Description:** Keep existing `ln -s` spellings for the intrinsic. Mark only leaf
cases blocked by product `command = "…"` sensor recipes as `🟡` with separately
tracked reasons — never skip a whole document.

**Acceptance criteria:**
- [ ] `ln -s` inventory items execute via intrinsic
- [ ] Each remaining product-POSIX skip names its issue/reason
- [ ] No whole-document skip introduced

**Verification:**
- [ ] Tests pass: affected leaves skip explicitly; link cases pass where allowed
- [ ] Manual check: skip list enumerated for Task 25

**Dependencies:** Task 14, 15

**Files likely touched:**
- Inventory-selected `*.spec.md` leaves

**Estimated scope:** Medium (3–5 files typical)

---

## Task 23: Remove global platform gate

**Description:** Remove `STEPS_RUN_ON_THIS_PLATFORM` / `POSIX_SHELL_ONLY` from
`steps.py`, `__init__.py`, `conftest.py`, and `tests/spec_runs.py`. Only after
inventory has zero “unsupported and unclassified” blocks.

**Acceptance criteria:**
- [ ] No remaining references to those names
- [ ] Executable docs collect and run on Windows; only explicit `🟡` skips remain
- [ ] `spec_runs` harness execution tests run on every host

**Verification:**
- [ ] Tests pass: `uv run pytest tests/spec_runs.py tests/test_spec_markers.py tests/test_spec_contexts.py -q`
- [ ] Grep clean for the three completion tokens in harness entry points
- [ ] Manual check: inventory final category empty

**Dependencies:** Tasks 18–22; inventory clean

**Files likely touched:**
- `tests/harness/steps.py`
- `tests/harness/__init__.py`
- `conftest.py`
- `tests/spec_runs.py`

**Estimated scope:** Small (1–2 files worth of logic; 4 files touched)

---

## Task 24: Bash-sentinel integration guard

**Description:** Add `tests/test_executable_specs_do_not_find_bash.py`: pin Windows
branch, put failing `bash.exe` sentinel first on PATH, record process argv, run a
representative parsed spec, assert success and no argv names the sentinel or any
`bash` executable.

**Acceptance criteria:**
- [ ] Guard fails if harness ever spawns Bash for command execution
- [ ] Uses platform pin + argv recording; does not require a real Windows host for
      the pin half

**Verification:**
- [ ] Tests pass: `uv run pytest tests/test_executable_specs_do_not_find_bash.py -q`
- [ ] Manual check: sentinel would fail if executed

**Dependencies:** Task 23

**Files likely touched:**
- `tests/test_executable_specs_do_not_find_bash.py` (new)

**Estimated scope:** Small (1–2 files)

---

## Task 25: Release evidence + acceptance counts

**Description:** Run platform-specific acceptance counts; enumerate remaining `🟡`
cases with issues; regenerate inventory; confirm Bash sentinel never executed;
record Linux/Windows pass/skip counts for the PR.

**Acceptance criteria:**
- [ ] Windows skips ≥115 fewer executable-doc cases than #137 baseline
- [ ] Inventory totals reconcile; no unsupported-unclassified
- [ ] Remaining skips listed with tracked reasons
- [ ] Completion grep: no `STEPS_RUN_ON_THIS_PLATFORM`, `POSIX_SHELL_ONLY`, or
      harness `["bash", "-c"` left

**Verification:**
- [ ] Tests pass: `uv run pytest` in a quiet checkout
- [ ] CI: executable-spec suite green on Windows, Linux, macOS
- [ ] Manual check: PR body contains the release-evidence section from the product spec

**Dependencies:** Tasks 23–24

**Files likely touched:**
- PR description / inventory attachment (code only if counts helpers added)

**Estimated scope:** Small (process + evidence)

---

## Checkpoint: Complete

- [ ] All product acceptance criteria met
- [ ] Technical verification section satisfied
- [ ] Ready for review / merge
