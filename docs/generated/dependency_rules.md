# Dependency Rules

## Summary
These rules formalize observed architecture boundaries from imports and runtime usage. They encode allowed and forbidden dependency directions for future impact analysis.

```mermaid
flowchart TB
  subgraph Allowed Direction (Top -> Down)
    EP[Entry points: main + routes]
    SV[Services]
    DM[Domain models + schemas]
    INFRA[Infrastructure: db, queue, plugin store, backup, alembic]
    UTIL[Utilities]
  end

  EP --> SV
  EP --> DM
  EP --> INFRA
  SV --> DM
  SV --> INFRA
  EP --> UTIL
  SV --> UTIL

  subgraph Forbidden Direction
    F1[Domain models -> routes]
    F2[Utilities -> routes/services state]
    F3[Agent runtime -> core DB/models]
    F4[Route module -> sibling route module]
    F5[Queue adapter -> route/business logic]
  end
```

## Invariants
- Domain objects (`services.models`, `services.schemas`) must stay framework-agnostic relative to route concerns.
- Agent runtime communicates through HTTP contract only; it must not import core persistence internals.
- Queue adapters remain pure transport primitives (`enqueue`, `pop_many`) without policy logic.
- Routing policy lives in `services.routing`; route handlers should orchestrate, not duplicate policy internals.

## Hotspot Modules
- `aurora_core/routes/operations.py`: lease/retry/checkpoint/result orchestration; highest change risk.
- `aurora_core/services/backup_service.py`: multi-system side effects (DB + filesystem + maintenance flags).
- `aurora_core/main.py`: global wiring and startup lifecycle; startup failures cascade.
- `aurora_agent/worker.py`: execution loop reliability and API contract coupling.

## Risk Signals
- Bottlenecks: central orchestration concentrated in operations route module.
- Fan-out risk: backup and superadmin flows touch many subsystems.
- Circular dependency risk: currently low in imports; rises if service modules start importing route helpers.
- Critical synchronous path: startup schema guard + bootstrap + scheduler start sequence in app lifespan.
