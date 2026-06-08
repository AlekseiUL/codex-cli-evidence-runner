# Walter Codex Scenario Task Template

Use this template when an operator assigns Walter a task where Codex may be useful.

## Header

```text
Task:
Requester:
Date:
Scenario class:
Execution lane: Hermes-tools-only | Codex-CLI
Codex allowed: yes/no + why
```

## Goal

What must exist at the end.

## Context

Only relevant context. No secrets. No broad dumps.

## Scope

Allowed read paths:
- ...

Allowed write paths:
- ...

Forbidden paths:
- secrets/auth/cookies/session stores
- unrelated profiles
- external contours unless approved
- user data outside task scope

Side effects:
- none allowed unless explicitly listed

## Preflight

- [ ] live date/time captured
- [ ] cwd confirmed
- [ ] git status or snapshot captured if code work
- [ ] allowed/forbidden paths restated
- [ ] rollback/backup plan stated if writing
- [ ] run directory/report path created or named
- [ ] execution lane selected: Hermes-tools-only / Codex-CLI
- [ ] if no git repo and writing, pre-write manifest/snapshot captured

## Codex prompt skeleton

```text
You are Walter's Codex executor for a scoped guarded-runner task.

Goal:
...

Allowed paths:
...

Forbidden paths:
...

Rules:
- Do not touch forbidden paths.
- Treat allowed read paths and allowed write paths separately.
- Do not ask for or print secrets.
- Do not perform external side effects.
- If you need approval, stop and report NEEDS_APPROVAL.
- Produce artifacts, not just prose.
- Run verification and report exact commands/results.
- If verification cannot prove the result, report INSUFFICIENT_EVIDENCE.

Expected output:
- changed files / artifacts
- verification commands and outputs
- risks / incomplete evidence
```

## Walter post-Codex verification

Walter must independently verify:

- files exist and read back;
- diff is expected;
- tests/build/lint/smoke passed or failure is named;
- no forbidden path touched;
- no file changed outside allowed write paths;
- no secret-looking output;
- final report is understandable to the operator.

## Completion format

```text
Outcome:
Artifacts:
Verification:
Risks:
Follow-up:
Memory/Wiki candidate:
```
