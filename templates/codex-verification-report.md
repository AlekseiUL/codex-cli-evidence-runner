# Walter Codex Verification Report Template

Use after any Walter/Codex run.

## Summary

```text
Outcome: done | partial | blocked | failed
Codex used: yes/no
Execution lane: Hermes-tools-only | Codex-CLI
Scenario class:
Run directory:
```

## Artifacts

- Created/changed files:
- Reports:
- Logs/transcripts:

## Scope check

Allowed paths:
- ...

Forbidden paths checked:
- ...

Result:
- [ ] no forbidden paths touched
- [ ] no files changed outside allowed write paths
- [ ] no secrets printed/written
- [ ] no external side effects performed

## Verification

Commands run:

```bash
# command
```

Results:

```text
# important output, normalized
```

Required checks:
- [ ] diff reviewed
- [ ] tests/lint/build run or explicitly not applicable
- [ ] smoke run completed or explicitly not applicable
- [ ] files read back
- [ ] report/artifact secret scan run
- [ ] changed-file secret scan run or explicitly not applicable
- [ ] if no git repo, pre/post manifest compared or explicitly not applicable

## Risk

- Remaining risk:
- Unverified claim:
- Required human approval if any:

## Decision

```text
ACCEPTED | NEEDS_FIX | NEEDS_APPROVAL | REJECTED
```

## Final summary for operator

```text
Outcome:
Artifacts:
Verification:
Risks:
Follow-up:
Memory/Wiki candidate:
```
