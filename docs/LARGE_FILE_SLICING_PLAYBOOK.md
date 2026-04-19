# Large File Slicing Playbook

Use this playbook before modifying large controller files (for example `main.py`).

## Goal

Reduce token and risk by moving route domains into focused modules.

## Slicing Order

1. `routes/auth.py`
2. `routes/agents.py`
3. `routes/jobs.py`
4. `routes/plugins.py`
5. `routes/superadmin_backup.py`
6. `routes/dashboard.py`

## Guardrails

1. Move one domain at a time.
2. Keep endpoint paths and response shapes unchanged.
3. Keep shared helpers in a dedicated `services/` or `utils/` module.
4. Add/import router with clear prefix and tags.
5. Run targeted tests after every slice.

## Per-Slice Checklist

1. Move handlers + local helper functions.
2. Wire router into app factory.
3. Run domain tests.
4. Smoke test startup.
5. Commit checkpoint.

## Rollback Plan

If a slice fails:

1. Revert only the current slice commit.
2. Keep prior successful slices.
3. Resume from last green checkpoint.

## Done Definition

1. `main.py` only contains app factory, dependency wiring, and router registration.
2. Route logic lives in domain modules.
3. Tests pass for moved domains.
