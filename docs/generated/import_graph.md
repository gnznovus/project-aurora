# Import Graph

## Summary
This graph captures the layered module topology validated from `aurora_core` and `aurora_agent` imports. It is intentionally compressed into domain layers to keep dependency reasoning tractable.

```mermaid
flowchart LR
  subgraph EntryPoints
    MAIN[aurora_core.main]
    OPS[aurora_core.routes.operations]
    AUTH[aurora_core.routes.auth]
    DASH[aurora_core.routes.dashboard]
    SA[aurora_core.routes.superadmin]
    AGW[aurora_agent.worker]
  end

  subgraph ServiceLayer
    SEC[services.security]
    WEB[services.web_auth]
    MNT[services.maintenance]
    ROUTE[services.routing]
    QUEUE[services.queue]
    PSTORE[services.plugin_store]
    BSVC[services.backup_service]
    BSCH[services.backup_scheduler]
    SGUARD[services.schema_guard]
    SCH[services.schemas]
  end

  subgraph DataLayer
    MODELS[services.models]
    DB[aurora_core.db]
    CFG[aurora_core.config]
  end

  subgraph UtilityLayer
    AUTIL[utils.auth_utils]
    TUTIL[utils.timeutils]
  end

  subgraph AgentRuntime
    ACLI[aurora_agent.client]
    ACFG[aurora_agent.config]
    ACACHE[aurora_agent.plugin_cache]
    AEXEC[aurora_agent.executor]
  end

  MAIN --> CFG
  MAIN --> DB
  MAIN --> ROUTE
  MAIN --> QUEUE
  MAIN --> PSTORE
  MAIN --> BSVC
  MAIN --> BSCH
  MAIN --> SGUARD
  MAIN --> AUTIL
  MAIN --> MODELS
  MAIN --> AUTH
  MAIN --> OPS
  MAIN --> DASH
  MAIN --> SA

  OPS --> SEC
  OPS --> MNT
  OPS --> ROUTE
  OPS --> QUEUE
  OPS --> PSTORE
  OPS --> SCH
  OPS --> MODELS
  OPS --> TUTIL
  OPS --> WEB

  AUTH --> WEB
  AUTH --> MODELS
  AUTH --> AUTIL
  AUTH --> TUTIL

  DASH --> SEC
  DASH --> BSVC
  DASH --> MODELS
  DASH --> WEB
  DASH --> TUTIL

  SA --> WEB
  SA --> BSVC
  SA --> MODELS
  SA --> PSTORE
  SA --> QUEUE
  SA --> MNT
  SA --> AUTIL
  SA --> TUTIL

  SEC --> MODELS
  SEC --> CFG
  WEB --> MODELS
  MNT --> MODELS
  ROUTE --> MODELS
  BSVC --> MODELS
  BSVC --> CFG
  BSCH --> BSVC
  BSCH --> MODELS
  SGUARD --> MODELS
  SGUARD --> CFG

  AGW --> ACLI
  AGW --> ACFG
  AGW --> ACACHE
  AGW --> AEXEC
  ACLI --> OPS
```

## Invariants
- Route modules depend on service/data/util layers, not on other route modules.
- Service layer is the only layer that should encode orchestration policy and side effects.
- `services.models` is the shared persistence contract for core runtime.
- `aurora_agent` runtime depends on HTTP API contract, not direct DB/model imports.

## Risk Signals
- Bottleneck: `aurora_core.routes.operations` is a high fan-in/fan-out orchestration hub.
- Fan-out risk: `aurora_core.main` wires many services and routers; startup failures can cascade.
- Circular dependency risk: currently low in code imports, but route-service coupling is dense around `web_auth` and audit paths.
- Critical synchronous path: `operations` route handlers perform sequential DB + queue + plugin metadata operations on request path.
