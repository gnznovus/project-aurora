# Observability Logging Standard

## Purpose
Define a consistent logging contract across `aurora_core` and `aurora_agent` so incidents can be traced end-to-end without code-level forensics.

## Scope
- `aurora_core/main.py` request middleware logs
- Core lifecycle routes (`operations`, `superadmin`, `dashboard`, `auth`)
- Agent worker lifecycle (`aurora_agent/worker.py`)
- Backup scheduler and schema guard operational logs

## Canonical Correlation Fields

Every lifecycle log line should include as many of these as applicable:
- `request_id`: HTTP request correlation id from middleware (`X-Request-Id`)
- `job_id`: Aurora job identifier (`JOB_...`)
- `execution_id`: Execution identifier (`exe_...`)
- `agent_id`: Agent identifier (`AGT_...`)
- `action`: stable action token (for example `job.enqueued`, `job.leased`, `execution.result.recorded`)
- `status`: normalized state/value relevant to action (`queued`, `leased`, `completed`, `failed`, `timeout`, `ok`)

Recommended additional fields:
- `plugin`, `version`
- `attempt`, `max_attempts`
- `exit_code`, `duration_ms`
- `backoff_seconds`, `lease_ttl_seconds`

## Log Line Format Contract

Use structured key-value style messages with stable keys:
- Pattern: `<action> key=value key=value ...`
- Keep key names stable across core and agent.
- Avoid embedding variable data in free text when a key can represent it.

Examples:
- `job.enqueued request_id=req_x job_id=JOB_... plugin=echo version=1.0.0 status=queued`
- `job.leased request_id=req_x agent_id=AGT_... job_id=JOB_... execution_id=exe_... status=leased`
- `execution.result.recorded request_id=req_x execution_id=exe_... job_id=JOB_... status=failed exit_code=2`

## Required Events by Flow

### 1. Enqueue Flow
Minimum events:
- `job.enqueued`
Required fields:
- `request_id`, `job_id`, `plugin`, `version`, `status`, `max_attempts`, `backoff_seconds`

### 2. Lease Acquisition Flow
Minimum events:
- `job.lease.none` (debug)
- `job.lease.race_lost`
- `job.leased`
- `job.recovered_for_retry` / `job.recovered_terminal_failure`
Required fields:
- `request_id`, `agent_id`, `job_id` (when available), `execution_id` (for leased/recovered), `status`

### 3. Plugin Resolution + Execution Flow (Agent)
Minimum events:
- `agent.step lease_received`
- `agent.step plugin_download` or `agent.step plugin_cache_hit`
- `agent.step execute`
- `agent.step checkpoint_upload` (when applicable)
- `agent.step report_result`
Required fields:
- `agent_id`, `job_id`, `execution_id`, `plugin`, `version`, `status`, `exit_code` (result)

### 4. Checkpoint Persistence Flow
Minimum events:
- `agent.step checkpoint_upload`
- Core-side checkpoint write acknowledgment (add if missing)
Required fields:
- `request_id` (core), `execution_id`, `job_id` (if resolvable), `status`

### 5. Completion/Retry Flow
Minimum events:
- `execution.result.recorded`
- `job.retry_scheduled` (retry branch)
- `job.failed_terminal` (terminal failure)
Required fields:
- `request_id`, `execution_id`, `job_id`, `status`, `attempt`, `max_attempts`, `exit_code`

### 6. Dashboard Visibility Flow
Minimum events:
- `http.request` for `GET /dashboard/api/overview`
Required fields:
- `request_id`, `path`, `status`, `duration_ms`

## Failure Propagation Logging Rules
- Lease conflicts and stale lease rejections must log with explicit reason (`race_lost`, `stale_lease`, `ownership_mismatch`).
- Plugin resolution failures must include `plugin`, `version`, and resolution step (`manifest` or `download`).
- Retry scheduling must include both `attempt` and `max_attempts`.
- Terminal failures must include final `status` and terminal attempt index.

## Current Gaps (As of 2026-05-23)
- Most lifecycle-critical core logs now include `request_id`; continue enforcing this for new endpoints.
- Agent logs intentionally do not include `request_id` (not an HTTP server); keep `agent_id/job_id/execution_id` mandatory for lifecycle actions.
- Core checkpoint persistence event is implemented (`execution.checkpoint.persisted`); maintain parity for future checkpoint-related endpoints.

## Verification Checklist
- [ ] For one successful job, traces can be reconstructed from enqueue -> lease -> execute -> result using `job_id` and `execution_id`.
- [ ] For one failed-then-retried job, retry schedule and second lease are visible with attempt counters.
- [ ] Every `execution.result.recorded` line includes `execution_id`, `job_id`, `status`, and `exit_code`.
- [ ] Every request touching job lifecycle can be joined by `request_id` in core logs.
- [ ] Dashboard overview request latency and status are visible via `http.request` log entries.

## Adoption Guidance
- Apply this standard incrementally: first lifecycle-critical events, then lower-priority operational logs.
- When adding new endpoints, define `action` names up front and keep them stable for dashboards/alerts.
- Prefer additive keys over message text churn to preserve alert/query compatibility.
