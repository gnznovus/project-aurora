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
- [x] Re-verify stability on current branch by running full unit suite now (`pytest tests/unit -q`) - passed (`41 passed in 9.98s`).

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

## Pre Nice-to-Have Hardening Sprint

Target: 1 short sprint before feature expansion.

### 1. Session and Auth Hardening
- [x] Set dashboard session cookie `Secure` automatically outside `dev/local/test`.
- [x] Add simple login rate limiting and lockout window for repeated failed `/login` attempts.
- [x] Add token-auth rate limiting for sensitive write endpoints (`/jobs`, `/plugins/register`, `/superadmin/*`).
- [x] Add unit tests for secure-cookie behavior and rate-limit responses.

Done when:
- [x] Non-dev deployments emit `Secure` session cookie.
- [x] Repeated bad login attempts return controlled denial.

### 2. Idempotency and Duplicate Suppression
- [x] Add optional `Idempotency-Key` support for `POST /jobs`.
- [x] Add optional `Idempotency-Key` support for `POST /plugins/register`.
- [x] Persist idempotency records with TTL and deterministic response replay.
- [x] Add tests for repeated requests with same key and divergent payload protection.

Done when:
- [x] Network retries cannot enqueue duplicate jobs for same idempotency key.
- [x] Conflict is returned when same key is reused with different payload.

### 3. Restore/Prune Operational Safety
- [x] Add time-bound secondary confirmation token for destructive backup actions.
- [x] Require confirmation token for prune and restore-apply endpoints.
- [x] Expand audit details with before/after summary for restore and prune.
- [x] Add tests for token expiry, invalid token, and happy path.

Done when:
- [x] Destructive actions require short-lived explicit confirmation.
- [x] Audit logs capture actor, request_id, and impact summary.

### 4. Lease/Retry Concurrency Correctness
- [x] Add stress-style unit tests for stale-lease recovery race windows.
- [x] Add tests for parallel `execution_result` submissions (duplicate terminalization prevention).
- [x] Validate `active_leases` counters stay non-negative under contention.

Done when:
- [x] No double-finalization of same execution under concurrent requests.
- [x] Retry/terminal transitions remain consistent under race conditions.

### 5. Readiness and Health Depth
- [x] Keep `/health` shallow and fast.
- [x] Add `/health/ready` with DB, Redis/queue adapter, and migration-head checks.
- [x] Add tests for degraded dependency behavior and readiness output schema.

Done when:
- [x] Operators can distinguish live vs ready states quickly.
- [x] Readiness clearly pinpoints failing subsystem.

## Architecture Docs (Generated)

- [x] `docs/generated/import_graph.md`
- [x] `docs/generated/route_graph.md`
- [x] `docs/generated/execution_flow.md`
- [x] `docs/generated/dependency_rules.md`
- [x] `docs/generated/db_relationships.md`
- [x] `docs/generated/critical_execution_paths.md`
- [x] `docs/generated/llm_execution_flow.md`

## Aurora LLM Track

### Prototype: Mock Provider
- [x] Create LLM concept and plugin design docs.
- [x] Create LLM execution flow documentation.
- [ ] Define `knowledge/commands/` metadata examples.
- [ ] Add `llm_plugin` mock provider implementation.
- [ ] Add keyword/tag command retrieval.
- [ ] Emit work-trace checkpoints.
- [ ] Add tests for metadata parsing, retrieval, mock output, and trace shape.

Done when:
- [ ] LLM prototype runs with zero paid provider dependency.
- [ ] Same plugin contract can later support `ollama_local`.
- [ ] Work trace shows retrieval and answer-generation stages without exposing hidden reasoning.

### Beta: Ollama Local Provider
- [ ] Add `ollama_local` provider adapter.
- [ ] Keep `mock` as default test provider.
- [ ] Add provider timeout and local model config.
- [ ] Add local usage/latency metadata where available.

### Future: Runtime Command Execution
- [ ] Add command metadata fields for executable commands (`executable`, `execution_kind`, `risk_level`, `requires_confirmation`, `required_role`).
- [ ] Add `execution_policy` support: `suggest_only`, `plan_only`, `allowlisted_execute`.
- [ ] Add plan-only validation for selected command, payload, role, and risk.
- [ ] Add allowlisted execution path only after plan validation is tested.
- [ ] Require confirmation token for destructive command execution.
- [ ] Add audit logs for command plan, execution start, execution result, and rejection.
- [ ] Add tests proving free-form generated commands cannot execute.

Done when:
- [ ] Prototype remains suggest-only.
- [ ] Future execution is metadata-driven, allowlisted, role-checked, and audited.
- [ ] Destructive execution cannot run without confirmation token.

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

1. Complete Pre Nice-to-Have Hardening Sprint items 1 to 5.
2. Re-run full unit suite and update hardening checklist statuses.
3. Start dashboard drilldown track.
4. Start routing strategy extensibility track.
