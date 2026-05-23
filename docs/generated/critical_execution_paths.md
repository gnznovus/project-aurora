# Critical Execution Paths

## Summary
This document isolates the highest-impact runtime path from enqueue to dashboard visibility. It separates synchronous request paths from asynchronous worker polling and marks where blocking, retries, persistence, and failures propagate.

```mermaid
flowchart TD
  classDef sync fill:#fde68a,stroke:#92400e,color:#111827
  classDef async fill:#bfdbfe,stroke:#1d4ed8,color:#111827
  classDef persist fill:#bbf7d0,stroke:#166534,color:#111827
  classDef retry fill:#fecaca,stroke:#991b1b,color:#111827
  classDef fail fill:#fda4af,stroke:#9f1239,color:#111827

  E1[1. POST /jobs enqueue]:::sync --> E2[Insert Job status=queued]:::persist
  E2 --> E3[Queue enqueue(job_id)]:::sync

  E3 --> A1[2. Agent poll: POST /agents/jobs/next]:::async
  A1 --> A2[Recover stale leases]:::sync
  A2 --> A3[Queue pop_many + DB candidate filter]:::sync
  A3 --> A4[CAS update Job queued->leased]:::persist
  A4 --> A5[Insert Execution leased + lease_expires_at]:::persist

  A5 --> P1[3. Plugin resolution]:::async
  P1 --> P2[GET manifest]:::sync
  P2 --> P3{Cache hit?}:::sync
  P3 -->|No| P4[GET plugin download]:::sync
  P3 -->|Yes| X1[Use cached artifact]:::sync
  P4 --> X1

  X1 --> R1[4. Plugin execution subprocess.run]:::async
  R1 --> R2[Produce stdout/stderr/exit_code]:::sync
  R2 --> C1{Checkpoint file exists?}:::sync
  C1 -->|Yes| C2[POST execution checkpoint]:::sync
  C2 --> C3[Insert ExecutionCheckpoint]:::persist
  C1 -->|No| K0[Skip checkpoint upload]:::sync

  C3 --> F1[5. POST execution result]:::sync
  K0 --> F1
  F1 --> F2{Result status}:::sync
  F2 -->|completed| F3[Execution->completed; Job->completed]:::persist
  F2 -->|failed/timeout + attempts left| F4[Job->queued + next_retry_at]:::persist
  F4 --> F5[Queue enqueue retry]:::retry
  F2 -->|failed/timeout + attempts exhausted| F6[Job->failed]:::persist
  F3 --> F7[Decrement Agent.active_leases]:::persist
  F5 --> F7
  F6 --> F7

  F7 --> D1[6. GET /dashboard/api/overview]:::async
  D1 --> D2[Aggregate counts/jobs/executions/checkpoints]:::sync
  D2 --> D3[Dashboard reflects queued/running/completed/failed + logs/progress]:::persist

  A2 -. stale lease path .-> SL1[Execution->timeout; job retry/fail transition]:::fail
  F1 -. lease expired/ownership mismatch .-> FP1[409/403 result rejected]:::fail
  P2 -. missing manifest/version .-> FP2[404 plugin resolution failure]:::fail
  R1 -. timeout/non-zero exit .-> FP3[failed|timeout status propagated]:::fail
```

## Synchronous vs Asynchronous Boundaries
- Asynchronous boundary: agent polling loop (`run_forever`) and queue-driven work intake.
- Synchronous boundaries: each HTTP request handler, DB transaction in route handlers, manifest/download calls, checkpoint/result submission.
- Asynchronous execution boundary: plugin subprocess execution is outside core process but blocking to the single agent worker loop during `subprocess.run`.

## Blocking Operations
- `POST /agents/jobs/next`: stale lease recovery + queue pop + DB candidate scan + lease transaction.
- Plugin artifact resolution: manifest lookup and optional download on cache miss.
- Plugin runtime: `subprocess.run(..., timeout=...)` blocks agent loop until completion/timeout.
- `POST /executions/{id}/result`: terminal state transition and retry decision occur synchronously.
- `GET /dashboard/api/overview`: multi-query aggregation (counts, agents, jobs, executions, latest checkpoint joins).

## Retry Boundaries
- Job retry boundary: only in `execution_result` when status is not completed and `attempt_count < max_attempts`.
- Retry scheduling state: `jobs.status=queued` + `jobs.next_retry_at` persisted before queue re-enqueue.
- Stale lease recovery boundary: in `next_job`, leased executions past `lease_expires_at` are converted to timeout and job is retried or failed terminally.

## State Persistence Points
- Job creation: `jobs` row insert at enqueue.
- Lease acquisition: `jobs.status` transition + `executions` row insert.
- Checkpoint: `execution_checkpoints` append insert.
- Completion/failure: `executions` terminal update + `jobs` terminal/retry update + `agents.active_leases` decrement.
- Dashboard visibility: read-model composed at query time from `jobs`, `executions`, `agents`, and latest checkpoint join.

## Failure Propagation Paths
- Plugin resolution failure (`404` manifest/download): agent cannot execute, result not submitted for that lease cycle.
- Plugin runtime timeout/non-zero exit: status becomes `timeout`/`failed`; core translates to retry or terminal failure.
- Result submission conflict (`409 stale lease`, `403 wrong owner`): execution cannot finalize via that agent; stale recovery later determines terminal state.
- Queue/database inconsistency window: queue is advisory; DB status gate prevents duplicate terminal transitions but can cause no-op pops under contention.
