# Project Aurora Planner

Last updated: 2026-05-23

## Baseline Snapshot

- Core/agent startup scripts are present and documented in `README.MD`.
- Route slicing is in place: `auth`, `operations`, `dashboard`, `superadmin`.
- Architecture intelligence docs generated under `docs/generated/`.

## Must Have (Status Checklist)

### 1. Stability and Regression Safety

- [x] Unit tests cover dashboard overview, startup schema guard, and lease/routing behavior.
- [x] Smoke-like API lifecycle coverage exists (`tests/unit/test_api_contract.py`, `tests/unit/test_routing_and_leases.py`).
- [x] CI gate for unit tests exists (`.github/workflows/unit-tests.yml`).
- [x] Re-verify stability on current branch by running full unit suite now (`pytest tests/unit -q`) - passed (`39 passed in 10.02s`).

Evidence:
- `tests/unit/test_schema_guard.py`
- `tests/unit/test_startup_security.py`
- `tests/unit/test_routing_and_leases.py`
- `.github/workflows/unit-tests.yml`

### 2. Production-Ready Auth and Secrets Baseline

- [x] Production startup rejects default superadmin credentials (`create_app` validation + tests).
- [x] Token/session and role checks are implemented across admin, agent, and superadmin flows.
- [x] README documents dev vs production credential setup.
- [x] Tighten/expand startup env validation beyond current credential guard (future hardening).

Evidence:
- `aurora_core/main.py`
- `aurora_core/services/security.py`
- `aurora_core/services/web_auth.py`
- `tests/unit/test_startup_security.py`

### 3. Backup/Restore Hardening

- [x] Backup create/list/validate/prune paths tested.
- [x] Restore dry-run and apply paths tested, including confirmation guard.
- [x] Maintenance mode mutation blocking tested.
- [x] Offsite sync + manifest download tested for success and not-found cases.
- [x] Operator restore runbook exists in README.

Evidence:
- `tests/unit/test_backup_api.py`
- `aurora_core/routes/superadmin.py`
- `README.MD` (Restore Runbook section)

### 4. Observability Minimum

- [x] Request correlation id is emitted (`X-Request-Id` middleware).
- [x] Structured logs exist for enqueue/lease/result and backup operations.
- [x] Dashboard overview exposes key health counters and latest execution/log context.
- [x] Add explicit cross-service trace stitching convention (job_id/execution_id/request_id across all lines) as a formal logging standard doc.

Evidence:
- `aurora_core/main.py`
- `aurora_core/routes/operations.py`
- `aurora_core/routes/dashboard.py`
- `aurora_agent/worker.py`
- `docs/observability_logging_standard.md`

## Architecture Docs (Generated)

- [x] `docs/generated/import_graph.md`
- [x] `docs/generated/route_graph.md`
- [x] `docs/generated/execution_flow.md`
- [x] `docs/generated/dependency_rules.md`
- [x] `docs/generated/db_relationships.md`
- [x] `docs/generated/critical_execution_paths.md`

## Nice to Have (Open)

### 1. Dashboard Drilldowns
- [ ] Add click-through details for agents/jobs/executions/backups.
- [ ] Add filter/search for failed runs and logs.

### 2. Routing Strategy Upgrades
- [ ] Add pluggable routing strategies beyond static deterministic rules.
- [ ] Add weighted/load-aware strategy option.

### 3. Plugin Runtime Improvements
- [ ] Add richer plugin execution metadata and failure categorization.
- [ ] Add retry policy profiles per plugin/job type.

### 4. Operational Guardrails
- [ ] Add stronger dashboard confirmation workflows for high-risk actions.
- [ ] Add policy controls for backup retention/offsite requirements in UI.

### 5. HA Readiness Track
- [ ] Define multi-core deployment topology and failover behavior.
- [ ] Document state consistency constraints for HA mode.

## Recommended Next Execution Order

1. Re-verify all unit tests on current branch and lock baseline.
2. Formalize logging/trace correlation standard.
3. Start dashboard drilldown track.
4. Start routing strategy extensibility track.
