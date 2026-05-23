# DB Relationships

## Summary
This ER graph is derived from SQLAlchemy models (`aurora_core/services/models.py`). It focuses on entities that govern orchestration lifecycle, auth/audit, and backup operations.

```mermaid
erDiagram
  AGENTS ||--o{ EXECUTIONS : runs
  JOBS ||--o{ EXECUTIONS : has
  EXECUTIONS ||--o{ EXECUTION_CHECKPOINTS : snapshots
  PLUGINS ||--o{ PLUGIN_VERSIONS : versioned_as
  PLUGINS ||--o{ JOBS : targeted_by
  PLUGIN_VERSIONS ||--o{ JOBS : resolves_to

  AGENTS {
    string id PK
    string api_key UK
    json tags
    int max_concurrency
    int active_leases
    datetime last_heartbeat_at
  }

  PLUGINS {
    int id PK
    string name UK
  }

  PLUGIN_VERSIONS {
    int id PK
    int plugin_id FK
    string version
    string digest
    string filename
  }

  JOBS {
    string id PK
    int plugin_id FK
    int plugin_version_id FK
    enum status
    int attempt_count
    int max_attempts
    datetime next_retry_at
  }

  EXECUTIONS {
    string id PK
    string job_id FK
    string agent_id FK
    enum status
    datetime lease_expires_at
    int exit_code
  }

  EXECUTION_CHECKPOINTS {
    int id PK
    string execution_id FK
    json payload
  }

  USERS {
    int id PK
    string username UK
    string role
    bool is_active
  }

  AUDIT_LOGS {
    int id PK
    string action IDX
    string actor_username
    json details
    datetime created_at
  }

  BACKUPS {
    string id PK
    enum status IDX
    string storage_path
    json manifest_json
  }

  SYSTEM_FLAGS {
    string key PK
    json value_json
    datetime updated_at
  }
```

## Invariants
- Lease state is modeled on `executions`; retry/terminal state is modeled on `jobs`.
- `plugin_versions` has uniqueness invariant `(plugin_id, version)`.
- Checkpoints are bound to executions, and job-level progress is reconstructed via join.
- Auth/session records are split: `users` persistent in DB, dashboard session map in app memory.

## Risk Signals
- Bottleneck: `jobs` and `executions` become hot tables under high throughput.
- Fan-out risk: result handling updates multiple rows (`executions`, `jobs`, `agents`) in one transaction.
- Circular dependency risk: relational graph is acyclic; operational cycles occur only in state machine transitions (queued->leased->queued).
- Critical synchronous path: restore/maintenance toggles via `system_flags` gate write endpoints system-wide.
