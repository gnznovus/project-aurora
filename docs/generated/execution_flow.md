# Execution Flow

## Summary
This flow is validated from `aurora_agent.worker`, `aurora_agent.client`, and `aurora_core.routes.operations`. It captures registration, lease acquisition, plugin execution, checkpointing, and result finalization.

```mermaid
sequenceDiagram
  participant Agent as AgentWorker
  participant Core as FastAPI operations routes
  participant Queue as QueueAdapter
  participant DB as PostgreSQL via SQLAlchemy
  participant Plugin as Subprocess Plugin Runtime

  Agent->>Core: POST /agents/register (bootstrap token)
  Core->>DB: insert Agent(api_key, tags, concurrency)
  Core-->>Agent: agent_id + api_key + poll config

  loop poll cycle
    Agent->>Core: POST /agents/heartbeat
    Core->>DB: update heartbeat + resource metrics

    Agent->>Core: POST /agents/jobs/next
    Core->>DB: recover stale leased executions
    Core->>Queue: pop_many(25)
    Core->>DB: filter queued jobs + fallback query
    Core->>DB: CAS-style update job queued->leased
    Core->>DB: insert Execution(lease_expires_at)
    Core-->>Agent: lease(job, plugin, resume_checkpoint)

    Agent->>Core: GET /plugins/{name}/manifest
    Agent->>Core: GET /plugins/{name}/download (on cache miss)
    Agent->>Plugin: execute_plugin(timeout, payload, checkpoint env)
    Plugin-->>Agent: exit_code + stdout/stderr + checkpoint file

    alt checkpoint exists
      Agent->>Core: POST /executions/{id}/checkpoint
      Core->>DB: insert ExecutionCheckpoint
    end

    Agent->>Core: POST /executions/{id}/result
    Core->>DB: validate lease owner + lease freshness
    alt completed
      Core->>DB: execution=completed, job=completed
    else failed/timeout with retries left
      Core->>DB: execution=failed/timeout, job=queued,next_retry_at
      Core->>Queue: enqueue(job_id)
    else terminal failure
      Core->>DB: job=failed
    end
    Core->>DB: decrement agent.active_leases
    Core-->>Agent: ack
  end
```

## Invariants
- A result is accepted only for matching `execution_id`, owning agent, and non-expired lease.
- Job retry scheduling is controlled by `attempt_count < max_attempts` and `next_retry_at`.
- Checkpoints are append-only snapshots tied to execution id.
- Queue membership is advisory; DB job status is the source of truth for eligibility.

## Risk Signals
- Bottleneck: lease issuance path (`/agents/jobs/next`) does stale recovery + candidate filtering + CAS update.
- Fan-out risk: result submission mutates execution, job, agent counters, and queue state.
- Critical synchronous path: subprocess execution is off-core, but completion handling is synchronous and transaction-sensitive.
- Circular risk: no direct runtime cycle, but repeated queue re-enqueue + stale recovery loops can amplify churn under persistent failures.
