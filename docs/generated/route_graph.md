# Route Graph

## Summary
This graph groups FastAPI routes by boundary and shows the dominant downstream dependencies per route family.

```mermaid
flowchart LR
  subgraph API_Surface
    HEALTH[/GET /health/]
    LOGIN[/GET+POST /login/]
    DSTAT[/GET /dashboard/auth/status/]
    DOV[/GET /dashboard/api/overview/]

    PREG[/POST /plugins/register/]
    JENQ[/POST /jobs/]
    AREG[/POST /agents/register/]
    AHB[/POST /agents/heartbeat/]
    ANEXT[/POST /agents/jobs/next/]
    PMAN[/GET /plugins/{name}/manifest/]
    PDL[/GET /plugins/{name}/download/]
    ERES[/POST /executions/{id}/result/]
    ECP[/POST /executions/{id}/checkpoint/]
    ECPG[/GET /executions/{id}/checkpoint/latest/]
    JPG[/GET /jobs/{id}/progress/]

    SU[/POST /superadmin/users/]
    SAUD[/GET /superadmin/audit/logs/]
    SBU[/POST /superadmin/backups/*/]
  end

  subgraph Guards
    ADMIN[require_admin_token]
    AGENT[require_agent_auth]
    SESSION[require_superadmin_session]
    MAINT[ensure_not_maintenance_mode]
  end

  subgraph CoreDeps
    DB[(SQLAlchemy Session)]
    Q[QueueAdapter]
    R[DefaultStaticRoutingStrategy]
    P[PluginStore]
    B[BackupService]
    A[(AuditLog)]
  end

  HEALTH --> DB
  LOGIN --> DB
  DSTAT --> SESSION
  DOV --> DB
  DOV --> B

  PREG --> ADMIN
  PREG --> MAINT
  PREG --> DB
  PREG --> P
  PREG --> A

  JENQ --> ADMIN
  JENQ --> MAINT
  JENQ --> DB
  JENQ --> Q
  JENQ --> A

  AREG --> MAINT
  AREG --> DB
  AHB --> AGENT
  AHB --> MAINT
  AHB --> DB

  ANEXT --> AGENT
  ANEXT --> MAINT
  ANEXT --> DB
  ANEXT --> Q
  ANEXT --> R

  PMAN --> DB
  PDL --> DB
  PDL --> P

  ERES --> AGENT
  ERES --> MAINT
  ERES --> DB
  ERES --> Q

  ECP --> AGENT
  ECP --> MAINT
  ECP --> DB
  ECPG --> AGENT
  ECPG --> DB
  JPG --> ADMIN
  JPG --> DB

  SU --> SESSION
  SU --> MAINT
  SU --> DB
  SU --> A

  SAUD --> SESSION
  SAUD --> DB

  SBU --> SESSION
  SBU --> B
  SBU --> DB
  SBU --> A
```

## Invariants
- Agent-only execution routes require `X-Agent-Id` + `X-Agent-Key`.
- Admin token protects operational APIs outside session-authenticated dashboard flow.
- Superadmin endpoints are session-gated and audit-emitting.
- Maintenance mode blocks write-like operations by design.

## Risk Signals
- Bottleneck: `/agents/jobs/next` combines stale-lease recovery, candidate selection, leasing, and execution creation in one request path.
- Fan-out risk: superadmin backup routes fan out into backup, DB, filesystem, and audit side effects.
- Critical synchronous paths: `/executions/{id}/result` and `/superadmin/backups/{id}/restore` have transactional state transitions with failure-sensitive ordering.
