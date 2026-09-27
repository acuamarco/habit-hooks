# Technical spec: portable executable documentation

Product spec:
[`issue.md`](issue.md)

Issue: [#137](https://github.com/habit-hooks/habit-hooks/issues/137)

Status: Proposed

## Purpose

This document defines how to replace the executable-spec harness's implicit
Bash process with a small native Python command interpreter. The existing
Markdown context model, markers, assertions, temporary directories, and output
normalization remain in place.

The implementation must run the same harness on Windows, Linux, and macOS. In
this document, “POSIX” means the non-Windows branch used for Linux and macOS.

## Existing flow

The current flow is:

```text
Markdown
  -> markdown.read_elements
  -> parser.parse_spec
  -> runner.execute
  -> steps.Command.apply
  -> Context.run
  -> bash -c "set -o pipefail; ..."
```

Windows is stopped before that flow reaches `runner.execute`:

- `tests/harness/steps.py` defines `STEPS_RUN_ON_THIS_PLATFORM` and
  `POSIX_SHELL_ONLY`.
- `tests/harness/__init__.py` exports both names.
- `conftest.py::SpecItem.runtest` skips every executable-documentation case.
- `tests/spec_runs.py::run` skips the harness execution tests.

Issue #137 removes those gates and replaces only the final execution layer.

## Target flow

```text
Markdown command fence
  -> Block(info, content, source)
  -> Command(script, platform, source)
  -> platform selection
  -> command lexer
  -> command parser
  -> immutable command AST
  -> native runtime
  -> direct child processes and harness intrinsics
  -> subprocess.CompletedProcess-compatible result
  -> existing Screen/Stderr assertions
```

No stage searches for Bash, Git Bash, WSL, PowerShell, or `cmd.exe`. A
platform-tagged command may name a shell explicitly; the harness then treats
that shell as an ordinary executable and does not interpret its script
argument.

## Module design

Keep each concern below the repository's 200-line source-file limit.

### Existing modules to change

`tests/harness/markdown.py`

- Add source location to `Block`.
- Parse enough of the fence info string to recognize a command fence.
- Keep validation of command tags out of the Markdown reader.

`tests/harness/parser.py`

- Validate command fence info strings.
- Convert `bash`, `bash posix`, and `bash windows` fences into `Command`
  instances carrying platform and source metadata.
- Preserve all existing heading, preamble, marker, and leaf-case behavior.

`tests/harness/steps.py`

- Remove the global Windows skip constants.
- Keep `Context` and marker step classes.
- Delegate selected command text to `command_runtime.run`.
- Track how many command steps were selected and executed.
- Add `PATHSEP` to `✏️` substitution values.

`tests/harness/runner.py`

- Continue applying steps in document order.
- Refuse a non-skipped case if no command was selected for the current host.
- Continue checking the final command's default exit code.

`tests/harness/__init__.py`

- Stop exporting `STEPS_RUN_ON_THIS_PLATFORM` and `POSIX_SHELL_ONLY`.
- Do not export command-parser internals unless a test cannot use the module
  directly.

`conftest.py`

- Remove the whole-suite platform skip.
- Keep the explicit `🟡` skip before creating the case directory.
- Pass the spec path into `parse_spec` for diagnostics.

`tests/spec_runs.py`

- Remove its platform skip.
- Let all harness execution tests run on every host.

### New modules

`tests/harness/command_model.py`

- Frozen enums and dataclasses for source spans, words, redirections, commands,
  pipelines, `&&` chains, and scripts.
- No subprocess or filesystem behavior.

`tests/harness/command_lexer.py`

- Character-by-character lexer for the closed command language.
- Quote and variable-part recognition.
- Operator recognition and source offsets.
- Rejection of unsupported shell syntax.

`tests/harness/command_parser.py`

- Recursive-descent parser from tokens to `command_model` objects.
- Command-prefix assignment recognition.
- Operator precedence and syntax validation.

`tests/harness/command_runtime.py`

- Word expansion.
- `;`, newline, and `&&` evaluation.
- Pipeline status calculation using pipefail.
- Command-scoped environment construction.
- Dispatch to a child-process pipeline or a harness intrinsic.

`tests/harness/command_process.py`

- Executable resolution.
- Redirection handle construction.
- Direct `subprocess.Popen` pipeline creation.
- Waiting, cleanup, and captured-output decoding.

`tests/harness/command_links.py`

- Exact `ln -s SOURCE LINK` intrinsic.
- Native `Path.symlink_to` implementation with injectable filesystem behavior
  for tests.

The dependency direction is:

```text
steps -> command_runtime -> command_process -> command_model
                         -> command_links   -> command_model
command_parser -> command_lexer -> command_model
runner -> steps
parser -> markdown + steps
```

`command_model`, `command_lexer`, and `command_parser` must not import
subprocess, pytest, or product sensor modules.

## Source model

Add:

```python
@dataclass(frozen=True)
class SourceSpan:
    source: str
    line: int
    column: int = 1
```

`markdown-it` exposes a fence node's zero-based source-line map. Convert its
start to a one-based line and attach it to `Block`.

Change:

```python
def parse_spec(text: str, source: str = "<inline>") -> list[SpecCase]:
    ...
```

Unit tests may retain the default. `SpecFile.collect` passes `str(self.path)`.
Lexer and parser offsets are relative to the fence and are translated through
its `SourceSpan`.

Every command-language `SpecError` includes the source, line, column, offending
line, and a caret. Runtime setup errors at least include the source and fence
line.

## Platform tags

Represent the tag as:

```python
class CommandPlatform(Enum):
    POSIX = "posix"
    WINDOWS = "windows"
```

`Command.platform` is `CommandPlatform | None`.

Fence validation is strict:

- `bash` means untagged.
- `bash posix` means Linux and macOS.
- `bash windows` means Windows.
- Tags are lowercase and case-sensitive.
- More than two info-string tokens are invalid.
- Any unknown second token raises `SpecError` while parsing the spec.

Platform matching imports the module, not the function:

```python
from habit_hooks import host_platform
```

It calls `host_platform.is_windows()` at application time so
`tests/platform_probe.py` can pin either branch.

A nonmatching `Command.apply` returns before:

- checking the preceding command's default exit;
- parsing or resolving the command;
- consuming pending stdin;
- changing `Context.last`;
- changing `Context.exit_checked`; or
- incrementing `Context.commands_run`.

This permits adjacent `posix` and `windows` alternatives to share one following
assertion.

After all steps, `runner.execute` raises `SpecError` if
`Context.commands_run == 0`. An inherited or untagged setup command counts as a
real command; the harness does not infer author intent beyond the product
spec's no-command rule.

## Command language

### Grammar

Use this grammar:

```text
script       := separators? sequence separators? EOF
sequence     := and_chain (separator and_chain)*
and_chain    := pipeline (AND_IF linebreak* pipeline)*
pipeline     := command (PIPE linebreak* command)*
command      := assignment* command_word command_item*
command_item := word | file_redirection | fd_duplication
assignment   := assignment_word
file_redirection := file_redirect_operator word
fd_duplication   := FD_DUP
separator    := SEMI | NEWLINE+
```

Operator precedence, from tightest to loosest, is:

1. redirection;
2. pipeline (`|`);
3. success-dependent sequencing (`&&`);
4. unconditional sequencing (`;` or an unquoted newline).

`a | b && c ; d` therefore:

1. runs the `a | b` pipeline;
2. runs `c` only if the pipefail status is zero; and
3. runs `d` regardless.

The script result is the result of the last pipeline actually executed.

Newline is a separator except immediately after `|` or `&&`, where it is
continuation whitespace. Blank lines are ignored. Empty commands and repeated
separators such as `;;` are errors.

### Tokens

The lexer emits:

```text
WORD
PIPE          |
AND_IF        &&
SEMI          ;
NEWLINE
REDIR_IN      <
REDIR_OUT     >
REDIR_APPEND  >>
FD_DUP        2>&1, 1>&2, >&2
EOF
```

Only descriptors 0, 1, and 2 are valid. A numeric prefix immediately adjacent
to a file-redirection operator is a descriptor; otherwise it remains a word.
`FD_DUP` is one complete token and consumes no following word: `2>&1` copies
the current descriptor 1 destination to descriptor 2, `1>&2` does the reverse,
and `>&2` is exactly the shorthand for `1>&2`. Recognize these longest forms
before `>` and `&`; separated or unsupported forms such as `2> &1`, `2>& 1`,
`0>&1`, and `3>&1` are syntax errors rather than a redirection followed by
arguments.

### Words and quotes

A word contains literal and variable parts:

```python
@dataclass(frozen=True)
class Word:
    parts: tuple[Literal | Variable, ...]
```

Rules:

- Unquoted whitespace separates words.
- Single quotes preserve all enclosed characters literally.
- Double quotes preserve whitespace and operators while expanding `$NAME` and
  `${NAME}`.
- Unquoted `$NAME` and `${NAME}` also expand.
- Adjacent quoted and unquoted parts form one argv item.
- Expansion never performs word splitting or filename expansion.
- Undefined variables expand to an empty string.
- An explicitly quoted empty string creates an empty argv item.
- Unterminated quotes and invalid `${...}` forms are `SpecError`.

Backslash handling is deliberately narrower than Bash:

- Outside quotes it escapes whitespace, quotes, command operators, `$`, and
  backslash.
- Before any other character it remains literal, preserving Windows paths.
- Inside double quotes it escapes only `"`, `$`, backslash, and newline.
- Inside single quotes it is literal.
- Backslash followed by newline is a continuation.

This preserves quoted jq expressions as opaque arguments even when they contain
`|`, `;`, `$name`, braces, regular-expression characters, or text resembling a
redirection.

### Variables

Command words expand against a copy of `Context.env` plus:

- `PWD`: the current case directory;
- `PATHSEP`: `os.pathsep`; and
- `PYTHON`: `sys.executable`.

`PATHSEP` makes inherited environment setup portable:

```text
$PWD/node_modules/.bin$PATHSEP$PATH
```

`PYTHON` gives migrated fixture-generation and output-filtering steps a stable
cross-platform executable instead of assuming `python` is on PATH.

`SetEnv.apply` exposes the same three reserved values through
`string.Template.safe_substitute`. Values assigned by `✏️` remain persistent
for the case. A command-prefix assignment is temporary and affects only that
child process.

Environment names follow the host's rules at both lookup and update:

- on POSIX, names are case-sensitive;
- on Windows, names are case-insensitive, so `$PATH`, `$Path`, and `$path`
  read the same inherited value; and
- a Windows update first removes every existing case-insensitive spelling,
  then stores one value under the spelling supplied by the update.

Use one environment-overlay helper for `SetEnv.apply`, command-prefix
assignments, reserved values, executable resolution, and the mapping passed to
`Popen`. It must collapse duplicate Windows spellings deterministically before
use, so `PATH=value command` cannot leave an inherited `Path` beside `PATH`.
Reserved `PWD`, `PATHSEP`, and `PYTHON` are applied after the inherited
environment and therefore cannot be shadowed by its casing. On Windows,
`PATH` and `PATHEXT` resolution uses this same case-insensitive view rather
than performing a separate lookup with potentially different results.

Assignments must precede the command name and match
`[A-Za-z_][A-Za-z0-9_]*=...`. Assignment-only commands, `export`, and
assignments after the command name are rejected. Assignment values expand
against the case environment; one assignment does not introduce a variable for
another assignment in the same prefix.

## Unsupported syntax

Reject unsupported shell-looking syntax instead of passing it as literal text:

- `||` and a bare `&`;
- heredocs and here-strings;
- command and process substitution;
- backticks;
- command grouping with unquoted parentheses;
- unquoted `*`, `?`, or glob brackets;
- a leading command-negation `!`;
- unquoted shell comments;
- loops, functions, conditionals, and shell keywords in command position; and
- arbitrary shell builtins.

Quoted forms remain ordinary argument text.

The only harness intrinsic is the exact symlink operation described below.
Utilities such as `cat`, `sed`, `grep`, `head`, `seq`, `printf`, `true`,
`false`, `echo`, and `exit` are not emulated. Existing harness tests and
documents must use a real cross-platform executable, generally `$PYTHON`, or a
platform-tagged alternative.

## AST

Use frozen dataclasses:

```python
@dataclass(frozen=True)
class Script:
    chains: tuple[AndChain, ...]

@dataclass(frozen=True)
class AndChain:
    pipelines: tuple[Pipeline, ...]

@dataclass(frozen=True)
class Pipeline:
    commands: tuple[SimpleCommand, ...]

@dataclass(frozen=True)
class SimpleCommand:
    assignments: tuple[Assignment, ...]
    argv: tuple[Word, ...]
    redirections: tuple[Redirection, ...]
    source: SourceSpan
```

Keep redirections in source order. Descriptor duplication is order-sensitive,
so normalizing them by descriptor would change behavior.

## Runtime result

`command_runtime.run` accepts:

```python
def run(
    script: str,
    context: CommandContext,
    source: SourceSpan,
) -> subprocess.CompletedProcess[str]:
    ...
```

`CommandContext` contains only:

- `cwd: Path`;
- `env: Mapping[str, str]`; and
- `stdin: str | None`.

The returned object uses the original script as `args` and contains aggregate
`returncode`, `stdout`, and `stderr`. This keeps `Context.last` and all existing
assertion steps unchanged.

`Context.run` performs:

1. `check_default_exit()` for the preceding selected command.
2. Call `command_runtime.run`.
3. Store the result in `last`.
4. Clear pending stdin in `finally` once execution was attempted.
5. Set `exit_checked = False`.
6. Increment `commands_run`.

Lexing or runtime setup errors still count as an attempted selected command,
but escape immediately as `SpecError`.

## Sequence execution

Create one binary temporary file for aggregate stdout and one for aggregate
stderr for the whole command fence. All top-level commands initially inherit
those destinations.

Temporary files are preferable to unread parent pipes:

- child output cannot fill a pipe and deadlock;
- all stages may write stderr safely;
- sequential output naturally appends;
- descriptor duplication can copy stable destinations; and
- large output need not remain in memory while children run.

For every `AndChain`:

1. Run its first pipeline.
2. Stop that chain at the first nonzero pipeline status.
3. Continue with the next semicolon/newline-separated chain regardless.

After execution:

1. flush and rewind both capture files;
2. read bytes;
3. decode as UTF-8 with `errors="replace"`; and
4. return the final status and decoded streams.

Do not add a default timeout; the existing harness has none.

## Pipeline execution

Before spawning any stage:

1. Expand every word and command-prefix assignment.
2. Identify any intrinsic.
3. Resolve every external executable.
4. Validate and open every redirection target.
5. Create all inter-stage pipes.

Resolving the complete pipeline first prevents a half-started pipeline when a
later executable is missing.

For each external stage:

1. Begin with descriptor 0 from pending stdin or inherited stdin.
2. Begin descriptor 1 with the next pipeline pipe or aggregate stdout.
3. Begin descriptor 2 with aggregate stderr.
4. Apply that command's redirections from left to right.
5. Spawn with `shell=False`, the resolved executable path, the command-scoped
   environment, and the case directory.
6. Close every parent copy of a pipe end as soon as all consumers are spawned.

When `⌨️` supplied text, encode it as UTF-8 and set the first stage's stdin to
`PIPE`. After all stages are running, use `Popen.communicate(input=...)` for the
first stage and `wait()` for the others. Final stdout and all uncaptured stderr
go to temporary files, so no child output pipe is waiting for the parent to
drain it. Ignore `BrokenPipeError` when the first stage exits before consuming
all input.

On interruption or setup failure after spawning:

1. close parent pipe handles;
2. terminate every started direct child;
3. wait briefly;
4. kill survivors; and
5. reap all children before reraising the original exception.

This change promises cleanup of direct children only. Process-tree supervision
and timeouts are separate concerns and must not be implied by this work.

### Pipefail

Wait for every stage and retain every return code.

- If all stages return zero, pipeline status is zero.
- Otherwise pipeline status is the rightmost nonzero return code.

`&&` uses this aggregate status. The final `CompletedProcess.returncode` is the
status of the last pipeline actually run.

## Redirection

Support:

```text
< file
> file
>> file
1> file
1>> file
2> file
2>> file
2>&1
1>&2
>&2
```

Redirection may appear among command arguments. It is removed from argv and
applied in source order.

Each descriptor maps to a concrete destination object. Duplication copies the
current destination; it does not retain a live reference to another descriptor.
Therefore:

```text
tool 2>&1 >/dev/null
```

keeps stderr pointed at the original stdout destination, while:

```text
tool >/dev/null 2>&1
```

points both streams at the null device.

Relative redirect paths resolve against the case directory. Opens are binary.
`>` truncates, `>>` appends, and `<` reads. Open failures raise `SpecError`
before any stage starts.

Do not translate `/dev/null` to `NUL`. Existing occurrences must become
platform-tagged alternatives or use a harness marker where equivalent.

## Executable resolution

Resolution receives expanded `argv[0]`, the command-scoped environment, and the
case directory.

If the name includes a path separator:

- resolve a relative path against the case directory;
- require a regular file; and
- on POSIX, require executable permission.

For a bare name:

- search the command environment's PATH in order;
- use `os.pathsep`;
- treat an empty PATH segment as the case directory; and
- return an absolute path.

On Windows:

- read PATH and PATHEXT case-insensitively;
- try an explicit extension as written;
- otherwise try PATHEXT entries in their declared order;
- compare extensions case-insensitively; and
- accept direct execution only for native executable forms such as `.exe` and
  `.com`.

If resolution finds only `.cmd`, `.bat`, or `.ps1`, raise an actionable
`SpecError`. The message tells the author to name `cmd.exe` or PowerShell
explicitly in a `bash windows` step. The harness must never add a shell around
such a file.

On POSIX, do not retry a failed executable format through `/bin/sh`.

A missing executable is a `SpecError`, not synthetic exit 127. This makes a
missing test prerequisite fail visibly and prevents an assertion from blessing
an environment failure as product behavior.

## Symlink intrinsic

Recognize exactly:

```text
ln -s SOURCE LINK
```

after word expansion and before executable resolution. This spelling is a
documented harness intrinsic; the runtime does not search for `ln`.

Constraints:

- exactly two operands;
- no other options;
- no redirection;
- no command-prefix assignments;
- no participation as a pipeline stage;
- allowed within `&&`, `;`, and newline sequencing.

Resolve the link path against the case directory. Preserve a relative source
as relative in the created link. Determine whether the target is a directory
relative to the link's parent, then call:

```python
Path.symlink_to(source, target_is_directory=is_directory)
```

This matters on Windows. Do not replace a symlink with a copied directory or
junction because those would stop measuring the layout used by pnpm and issue
#142.

Permission failures, including Windows error 1314, raise an actionable
`SpecError`. Unit tests that create real links use
`A_MACHINE_THAT_CAN_MAKE_A_SYMLINK`; logic tests inject a fake linker so both
platform branches run everywhere.

## Error taxonomy

Use `SpecError` when the document or its test environment cannot be executed:

- invalid or unknown platform tag;
- malformed or unsupported command syntax;
- missing executable;
- implicit Windows script requiring a shell;
- redirection open failure;
- symlink failure; or
- no selected command.

Keep the error classification clear through behavior and tests without adding
or restoring a docstring; the repository comment policy treats docstrings as
comments.

Use `SpecFailure` only after a product command ran:

- unexpected default exit code;
- explicit exit assertion mismatch;
- stdout mismatch; or
- stderr mismatch.

A nonzero command result remains data until `Screen`, `Stderr`, or the next
selected command calls `check_default_exit`. This preserves the current ability
to assert expected failures.

## Test design

### Lexer and parser tests

Add `tests/test_spec_command_language.py` covering:

- quoting and adjacent word parts;
- empty quoted arguments;
- `$NAME`, `${NAME}`, `$PWD`, `$PATHSEP`, and `$PYTHON`;
- literal `$name` inside single-quoted jq;
- Windows backslashes;
- multiline quoted arguments;
- newline after `|` and `&&`;
- operator precedence;
- interleaved redirections;
- descriptor duplication as a complete operand-free token, including rejection
  of separated and unsupported descriptor forms;
- command-prefix assignments; and
- every rejected shell construct.

These tests parse ASTs and spawn nothing.

### Platform-selection tests

Add `tests/test_spec_command_platform.py` covering:

- untagged commands on both pinned platforms;
- `posix` selection;
- `windows` selection;
- adjacent alternatives followed by one shared assertion;
- unknown and extra tags;
- a nonmatching command preserving pending stdin and the previous result; and
- refusal when no command is selected.

Use `platform_probe.on_windows` and `platform_probe.off_windows`. Do not patch
`sys.platform` or duplicate the platform seam.

### Runtime tests

Add `tests/test_spec_command_runtime.py` covering:

- one direct executable;
- PATH resolution and command-scoped PATH;
- on a pinned Windows branch, case-insensitive expansion and replacement of an
  inherited `Path` by `PATH` with no duplicate key passed to the child;
- on a pinned POSIX branch, distinct `Path` and `PATH` values;
- UTF-8 replacement;
- stdin delivery;
- output aggregation across sequences;
- `&&` short-circuit and `;` continuation;
- rightmost-nonzero pipefail;
- an early failing producer with a successful consumer;
- large stdin, stdout, and stderr without deadlock;
- downstream early exit;
- every supported redirection;
- the order difference between `2>&1 >file` and `>file 2>&1`;
- missing executable before any pipeline stage starts;
- `.cmd` and `.bat` refusal on a pinned Windows branch;
- explicit `cmd.exe` remaining an ordinary executable; and
- cleanup of already-started direct children after a spawn failure.

Use `sys.executable -c ...` or `$PYTHON -c ...` as the portable fixture process.
Do not depend on `echo`, `true`, `false`, `cat`, or another shell utility.

### Symlink tests

Add `tests/test_spec_command_links.py` covering:

- relative source preservation;
- file and directory targets;
- invalid intrinsic forms;
- refusal inside a pipeline;
- injected Windows privilege failure; and
- one real link test guarded by
  `platform_probe.A_MACHINE_THAT_CAN_MAKE_A_SYMLINK`.

### Existing harness tests

Rewrite command fixtures in `tests/test_spec_markers.py` and
`tests/test_spec_contexts.py` to use `$PYTHON`. Once the global gate is removed,
every test in both modules runs on Windows.

Keep tests of the marker meanings and context meanings in those modules.
Command-language details belong in the new focused modules.

### Integration guard

Add `tests/test_executable_specs_do_not_find_bash.py`.

Run a representative parsed spec while:

- pinning the Windows branch;
- placing a failing `bash.exe` sentinel at the front of PATH; and
- recording process argv.

Assert the case passes and no spawned argv names the sentinel or any `bash`
executable. This proves the Windows path does not escape through WSL or Git
Bash.

## Document migration

The issue report cited 206 command blocks in 14 documents as its historical
baseline. Recount the current corpus during the migration inventory and migrate
by behavior, not file duplication.

### Migration inventory gate

Before committing to the full runtime, run the lexer/parser as an audit over
all command blocks and attach a source-and-line inventory to the implementing
pull request. Classify every block exactly once as:

- portable without changes;
- portable after a stated mechanical rewrite;
- a POSIX/Windows tagged pair;
- the exact `ln -s` intrinsic;
- an explicitly skipped product-level POSIX recipe; or
- unsupported and not yet classified.

The category counts must sum to the discovered corpus count, not to the
historical number 206, and the final category must be empty before the
platform-wide skip is removed. The audit must report parser errors together,
not stop at the first one.

Build a thin runtime spike before implementing the complete design. On both a
pinned POSIX branch and a pinned Windows branch, it must execute representative
direct invocation, pipeline, ordered redirection, command-scoped `PATH`
assignment, and missing-executable cases without resolving Bash. If the audit
finds a new syntax family, prefer migrating those blocks; broadening the
language requires an explicit revision to this specification and its test
matrix.

### First: native-compatible commands

Run direct `habit-*`, Git, jq, uv, and plugin-owned executable invocations
through the new runtime. Keep their assertions unchanged.

### Second: environment preambles

Replace:

```text
$PWD/node_modules/.bin:$PATH
```

with:

```text
$PWD/node_modules/.bin$PATHSEP$PATH
```

in the generic and TypeScript plugin preambles.

### Third: POSIX utility fixtures

Replace uses of `cat`, `head`, `printf`, `sed`, `grep`, and `seq` where a short
`$PYTHON -c ...` command expresses the same setup or deterministic scrub.
Keep a utility command only when the document is intentionally teaching that
utility.

### Fourth: platform paths

Pair `bash posix` and `bash windows` commands for:

- `/dev/null` versus `NUL`;
- POSIX venv `bin` versus Windows `Scripts`;
- POSIX-only PATH values; and
- any executable spelling whose actual filename differs by platform.

Expected output, stderr, exit code, and resulting files remain shared.

### Fifth: symlinks

Keep existing `ln -s` spellings and execute them through the intrinsic.

### Sixth: product-level POSIX recipes

Cases whose fixtures define `command = "..."` sensors remain outside this
change. Mark only affected leaf cases `🟡` with their separately tracked reason.
Do not skip a whole document or treat those recipes as harness commands.

## Implementation sequence

Each step should leave focused tests green:

1. Produce the migration inventory and run the cross-platform runtime spike.
2. Add source metadata and strict platform-tag parsing.
3. Add command model, lexer, parser, and rejection tests.
4. Add case-correct environment overlay, variable expansion, and direct
   single-process execution.
5. Add ordered redirection.
6. Add multi-process pipelines and pipefail.
7. Add `&&`, semicolon, and newline sequencing.
8. Add command-scoped assignments.
9. Add the symlink intrinsic.
10. Switch `Context.run` to the native runtime.
11. Rewrite the existing harness unit-test command fixtures.
12. Remove the global platform gate and exports only after the inventory has no
    unsupported, unclassified blocks.
13. Update `docs/executable_spec.md`.
14. Migrate executable documents in the order above.
15. Add the Bash-sentinel integration guard.
16. Run platform-specific acceptance counts and enumerate remaining `🟡` cases.

Do not retain a hidden Bash fallback during migration. If the native parser
cannot execute a block, the block must be migrated, tagged, or explicitly
skipped.

## Verification

For every edited Python file:

- run focused harness tests;
- run Ruff through the repository's normal test/lint command; and
- check IDE diagnostics.

Before completion:

- run `uv run pytest` in a quiet checkout;
- run the executable-spec suite on Windows, Linux, and macOS CI;
- regenerate the command-block inventory, reconcile its total with the
  discovered corpus, and confirm that no block is unsupported and unclassified;
- verify Windows skips at least 115 fewer documentation cases than the #137
  baseline;
- list every remaining explicit skip and its issue;
- compare shared assertions for every tagged pair; and
- confirm the Bash sentinel was never executed.

The implementation is complete only when `STEPS_RUN_ON_THIS_PLATFORM`,
`POSIX_SHELL_ONLY`, and `["bash", "-c", ...]` have no remaining references.

## Technical decisions

This design deliberately chooses:

- a purpose-built lexer instead of `shlex`, because quoting, operators,
  redirection, and Windows backslashes need one stable grammar;
- an immutable AST instead of interpreting token streams during spawning;
- direct `Popen` calls with `shell=False`;
- temporary files for top-level capture to avoid pipe deadlocks;
- left-to-right descriptor maps for correct duplication semantics;
- rightmost-nonzero pipefail to preserve current Bash behavior;
- `$PATHSEP` and `$PYTHON` as reserved harness substitutions;
- one exact `ln -s` intrinsic instead of emulating general shell utilities;
- explicit refusal of `.cmd`, `.bat`, and `.ps1` unless a document names their
  interpreter; and
- visible failure for missing prerequisites instead of synthetic shell exit
  codes or a new platform-wide skip.
