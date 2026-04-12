# Issues Memo - 2026-04-12

## Context

After adding agent CPU/RAM heartbeat metrics and dashboard usage display, runtime errors appeared in Core/Agent logs.

## Observed errors

### Core (`core.err.log`)

- `sqlalchemy.exc.ProgrammingError: column "cpu_load_pct" of relation "agents" does not exist`
- failing SQL: insert into `agents (... cpu_load_pct, ram_load_pct ...)`

### Agent (`agent.err.log`)

- repeated:
  - `500 Server Error: Internal Server Error for url: /agents/register`

## Root cause

- New model fields were deployed before schema migration applied in the runtime DB.
- Missing migration on environment:
  - `0005_agent_resource_metrics.py`

## Immediate recovery

1. Apply migrations:
   - `alembic upgrade head`
2. Restart services:
   - `.\scripts\run_all.ps1 -RestartExisting`

## Preventive improvements (next session)

1. Startup schema guard:
   - Core should check Alembic head vs DB current revision and log a clear actionable error.
2. Safer deploy docs:
   - Add pre-run checklist in README:
     - pull -> install deps -> `alembic upgrade head` -> restart.
3. Optional:
   - provide `scripts/migrate_and_restart.ps1` to reduce operator mistakes.

## Additional UX notes (queued)

1. Agent usage display switched to CPU/RAM percentages.
2. Operation chart changed to donut split (`queued/running/completed/failed`).
3. Further visual polish can be done later after runtime stability checks.
