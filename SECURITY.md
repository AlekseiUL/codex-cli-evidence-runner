# Security Policy

## Supported scope

Codex CLI Evidence Runner is a local-first guarded runner for OpenAI Codex CLI. Security reports are in scope when they relate to:

- leaking secrets or private paths through runner artifacts;
- unsafe diff application;
- path traversal or writes outside the declared project/run scope;
- broken forbidden-path or allowed-path checks;
- receipt validation bypasses;
- unsafe cleanup behavior;
- misleading PASS reports when verification failed.

## Out of scope

The project does not handle production deploys, account posting, payments, billing, or secret management. It also does not provide security support for OpenAI Codex CLI itself.

## Reporting

Please report issues through the canonical repository:

https://github.com/AlekseiUL/codex-cli-evidence-runner

If the repository is private during staging, report the issue directly to the maintainer who gave you access.

Do not include real secrets, private prompts, customer data, tokens, or sensitive logs in a report. Use a minimal reproduction with fake values.

## Safe defaults

- Generated `runs/` artifacts are ignored by git except `.gitkeep`.
- `apply-diff` requires dry-run-first review and explicit confirmation.
- The runner refuses unsafe status/gate/risk combinations.
- Tests include fake Codex fixtures and negative safety cases.
