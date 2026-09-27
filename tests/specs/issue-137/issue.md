# Product spec: portable executable documentation

Issue: [#137](https://github.com/habit-hooks/habit-hooks/issues/137)

Status: Proposed

## Summary

The executable documentation must run natively on Windows as well as POSIX
hosts. A spec keeps one platform-independent expected outcome. When producing
that outcome requires platform-specific command spelling, both command steps
live beside each other in the same document and the harness runs only the one
for its host.

The harness must execute the command language itself. It must not discover or
delegate all commands to a shell: a `bash` found on a Windows runner may be the
WSL launcher and therefore operates on a different filesystem.

## Problem

Pytest discovers the executable documentation on every CI host, but
`tests/harness/steps.py` currently skips every case when `os.name == "nt"` and
runs every command through:

```text
bash -c "set -o pipefail; <step>"
```

As reported in #137, this made the Windows leg skip 165 documentation cases and
22 harness tests while Linux ran them. The skipped surface includes the command
pipeline, mapper output and exit codes, snoozing, initialization, the
plugin-authoring contract, the sensor interface, and each plugin's behavior.
Windows-specific regressions can consequently merge while both CI legs are
green.

The issue report cited 206 command blocks across 14 executable documents as
the baseline at the time it was filed. The implementing audit must recount the
current corpus before classifying it. The reported corpus mostly used executable
invocation, pipelines, and redirection; the remaining portable-harness needs
were command sequencing, symlink setup, one command-scoped environment override,
and a small number of multi-command blocks. The report found no heredocs,
command substitution, process substitution, loops, or shell functions.

## Product goals

- Run every command step that the host can express instead of skipping the
  entire executable-documentation suite on Windows.
- Keep one user-facing document and one asserted outcome for each behavior.
- Let a reader see POSIX and Windows command spellings together when they
  differ.
- Preserve current failure semantics, especially pipe failure, exit-code
  assertions, stdin, stdout, stderr, environment inheritance, and case
  isolation.
- Fail malformed or unsupported command syntax explicitly. Never turn an
  unexecuted command into a passing case.

## Non-goals

- Do not create parallel Windows copies of any `*.spec.md` document.
- Do not change the product outcome asserted by a case by platform.
- Do not enable POSIX `command = "..."` sensor recipes on Windows. The product
  deliberately refuses those recipes, and their fixtures are tracked
  separately.
- Do not find Git Bash, WSL, or another shell and use it as the Windows
  executor.
- Do not make `bash` configured as a mapper fix runner portable. That is
  product configuration, not a harness command step.
- Do not weaken or remove an assertion merely to increase the Windows pass
  count.

## Command-step contract

### Platform selection

The existing command fence remains the command-step marker. It accepts an
optional platform tag as the second info-string token:

````markdown
```bash posix
printf '%s\n' "$VALUE"
```

```bash windows
python -c "print('the same value')"
```
````

The supported tags are exactly `posix` and `windows`.

- An untagged `bash` command step runs on every platform.
- A `posix` step runs only when the host is not Windows.
- A `windows` step runs only on Windows.
- An unknown tag is a spec error, not a skip.
- A nonmatching tagged step is omitted without changing pending stdin or the
  last command result.
- Adjacent platform alternatives are ordinary steps. Authors are responsible
  for giving both alternatives the same externally visible effect; subsequent
  `🖥️` and `🚨` assertions remain untagged and shared.

The `bash` label is retained for compatibility with existing documentation; it
identifies a command block, not a promise that the harness invokes Bash.
`docs/executable_spec.md` must state this directly.

### Portable command language

An untagged command must use only the documented portable subset:

- invoke an executable with arguments, including quoted arguments;
- connect commands with pipelines;
- redirect stdout and stderr;
- sequence commands only after success (`&&`);
- sequence commands regardless of status (`;`);
- apply an environment assignment to one command; and
- perform the repository's documented symlink setup operation.

The runner must preserve the current effective `pipefail` behavior: if any
pipeline stage fails, the command step fails unless a later explicit assertion
expects that exit code.

The portable language is closed, not “whatever a local shell accepts.”
Unsupported operators or syntax must produce a `SpecError` that identifies the
command step. Heredocs, command substitution, process substitution, glob
expansion, loops, functions, and arbitrary shell builtins are outside the
contract unless a later product change documents and tests them.

Platform-tagged steps may use host-specific executable names, paths, and
arguments. Tagging does not authorize implicit shell evaluation: a shell may
run only when the document names it explicitly as the executable.

### Environment and paths

- `✏️` variables continue to inherit the case environment and expand earlier
  variables plus `PWD`.
- PATH construction must use the host path separator. A value such as
  `$PWD/node_modules/.bin:$PATH` must not be emitted on Windows, where `;` is
  required and drive paths contain `:`.
- A Windows command must not be handed POSIX-only paths such as `/dev/null`,
  `/usr/bin`, or `$VIRTUAL_ENV/bin/...`.
- The same temporary working directory, pending stdin, and environment apply
  whichever platform alternative runs.
- Existing UTF-8 decoding with replacement and output normalization remain
  unchanged.

## Authoring requirements

`docs/executable_spec.md` is the source of truth and must be updated before the
new syntax is used elsewhere. Its platform-tagged example must show:

1. one POSIX step;
2. one Windows step;
3. one shared output and exit-code assertion; and
4. an untagged command that runs everywhere.

Authors should prefer an untagged portable command. Platform tags are for
spelling differences, not behavior differences. A case that cannot yet run on
one host remains visibly skipped through the existing `🟡` mechanism; it must
not silently disappear because its only command was tagged for another host.

## Required behavior

1. Pytest collects the same executable documents and leaf cases on every host.
2. `STEPS_RUN_ON_THIS_PLATFORM` and `POSIX_SHELL_ONLY` are removed from the
   harness API and all importers.
3. `Context.run` no longer hard-codes `bash`.
4. Untagged portable steps run on both Windows and POSIX.
5. Exactly the matching member of a platform-specific pair runs.
6. A failing stage in a pipeline fails the step on both platforms.
7. Existing `⌨️`, `🖥️`, `🚨`, `📄`, `✏️`, inheritance, isolation, and default
   exit-code semantics do not change.
8. A case with no command selected for its host cannot report success. It must
   be rejected as malformed or explicitly marked `🟡`.
9. The harness never treats the presence of a `bash` executable on Windows as
   evidence that POSIX commands are runnable.

## Migration

Migrate incrementally without splitting documents:

1. Add and document platform selection and the portable executor.
2. Convert command blocks already inside the portable subset to untagged
   steps.
3. Put paired `posix` and `windows` steps beside each other for PATH setup,
   null-device paths, virtual-environment executables, symlink setup, and other
   spelling differences.
4. Convert sequencing and multi-command setup without changing assertions.
5. Leave cases blocked by the separately tracked POSIX sensor-recipe problem
   explicitly skipped rather than pretending they ran.

External programs already used by acceptance documentation—such as Git, jq,
uv, and plugin-owned Node tools—remain test-environment prerequisites. A
missing prerequisite must fail or explicitly skip the affected case; it must
not revive the whole-suite Windows gate.

## Acceptance criteria

- `docs/executable_spec.md` documents the platform tag, portable subset, and a
  paired example.
- Unit tests cover untagged, POSIX-only, Windows-only, unknown-tag,
  no-selected-command, pipeline-failure, redirection, sequencing,
  command-scoped environment, and symlink behavior.
- Platform-dependent unit tests pin the platform through
  `tests/platform_probe.py`, following the repository's existing rule.
- Integration tests prove pytest runs a representative executable document on
  Windows without locating or spawning Bash.
- The Windows CI leg skips at least 115 fewer executable-documentation cases
  than the baseline in #137.
- No migrated case has different expected stdout, stderr, exit code, files, or
  product state by platform.
- `uv run pytest` remains green on Linux and macOS.
- The Windows CI leg remains green, and any still-unportable case is reported
  as an individual explicit skip.

## Release evidence

The implementing pull request must report, for Linux and Windows:

- passed and skipped executable-documentation case counts;
- the remaining explicitly skipped cases and their tracked reason; and
- confirmation that the Windows run did not resolve or spawn Bash for harness
  command execution.
