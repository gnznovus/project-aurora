# Project Aurora Planner

Last updated: 2026-05-03

## Current Baseline

- Core and agent can start via `.\scripts\run_all.ps1`.
- `aurora_core/main.py` is now slim and route slicing is in place.
- Domain routes exist: `auth`, `operations`, `dashboard`, `superadmin`.
- Recent regressions from restructuring were fixed (schema path + random enqueue).

## Must Have

### 1. Stability and Regression Safety

- Goal: prevent breakage after refactors and daily changes.
- Tasks:
  - Add/refresh unit tests for `dashboard overview`, `superadmin debug enqueue`, and startup schema guard.
  - Add a smoke test flow: register plugin -> enqueue job -> lease -> result.
  - Add CI gate to run unit tests on every push.
- Done when:
  - `pytest tests/unit -q` passes consistently.
  - Critical API paths above are covered by tests.
  - Breakages like detached SQLAlchemy objects are caught in tests.

### 2. Production-Ready Auth and Secrets Baseline

- Goal: remove insecure defaults for production usage.
- Tasks:
  - Enforce non-default superadmin credentials when not in local/dev mode.
  - Validate required env vars at startup with clear errors.
  - Confirm token/session handling is audited and role checks are consistent.
- Done when:
  - Startup fails fast for unsafe production config.
  - README has clear dev vs production auth setup.

### 3. Backup/Restore Hardening

- Goal: make backup/restore trustworthy under real operations.
- Tasks:
  - Add tests for create/validate/prune/restore and maintenance mode behavior.
  - Verify offsite sync + manifest download paths across normal and error cases.
  - Add one operator runbook section for restore drill.
- Done when:
  - Backup API contract is tested end-to-end.
  - Restore dry-run and apply paths are validated with clear operator steps.

### 4. Observability Minimum

- Goal: speed up incident diagnosis.
- Tasks:
  - Standardize structured logging for key events: job enqueue, lease, completion/failure, backup operations.
  - Add request correlation id (or execution/job id propagation) in logs.
  - Ensure dashboard and API can expose essential health counters.
- Done when:
  - A failed job can be traced across core and agent logs quickly.
  - Logs are consistent and useful without code digging.

## Nice to Have

### 1. Dashboard Drilldowns

- Add click-through details for agents, jobs, executions, and backup records.
- Include filter/search for recent logs and failed executions.

### 2. Routing Strategy Upgrades

- Add pluggable routing strategies beyond static deterministic rules.
- Introduce weighted or load-aware strategy option.

### 3. Plugin Runtime Improvements

- Add richer plugin execution metadata and error categories.
- Add optional retry policy profiles per plugin/job class.

### 4. Operational Guardrails

- Add confirmation workflows for high-risk actions in dashboard.
- Add policy controls for backup retention/offsite requirements in UI.

### 5. HA Readiness Track

- Plan and document steps for multi-core deployment model.
- Define failover behavior and state consistency requirements.

## Execution Order (Recommended)

1. Stability and Regression Safety
2. Production-Ready Auth and Secrets Baseline
3. Backup/Restore Hardening
4. Observability Minimum
5. Nice-to-have tracks in parallel based on priority

## Next Session Starter Tasks

1. Add unit test for `POST /superadmin/debug/enqueue-random` to prevent detached-session regressions.
2. Add unit test for schema guard migration path resolution.
3. Add a quick CI workflow for `pytest tests/unit -q`.
4. Update README troubleshooting command to use `python -m pip` consistently.
