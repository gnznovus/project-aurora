---
name: testing-aurora
description: Set up, run, and test Project Aurora (FastAPI job-orchestration MVP) end-to-end. Use when verifying Aurora Core/agent/dashboard changes or running its test suites. Note the repo's scripts/*.ps1 are Windows-only; this covers the Linux equivalents.
---

# Testing Project Aurora

Aurora = FastAPI control plane (`aurora_core`) + pull-based worker (`aurora_agent`) that runs versioned plugins as subprocesses. Postgres for state, Redis for the dispatch queue.

## Important: run scripts are Windows-only
`scripts/*.ps1` (`run_all.ps1`, etc.) are PowerShell and won't run on Linux/macOS. Use the commands below directly. The README Quick Start is also PowerShell-centric.

## Local setup (Linux)
```bash
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e ".[dev]"
docker compose up -d                 # Postgres 16 + Redis 7
cp .env.example .env                 # defaults match the compose stack
set -a && . ./.env && set +a         # load env (needed by alembic/uvicorn)
alembic upgrade head                 # 6 migrations
```

## Run the app
```bash
# Core (control plane + dashboard)
set -a && . ./.env && set +a
uvicorn aurora_core.main:create_app --factory --host 127.0.0.1 --port 8000

# Agent worker (separate shell; tag must match a job's required_tags, default is "default")
set -a && . ./.env && set +a
python -m aurora_agent.worker        # runs forever, polls Core
```
- Health: `GET /health` (shallow), `GET /health/ready` (DB/queue/schema/scheduler).
- Dashboard: http://127.0.0.1:8000/login — dev bootstrap creds `superadmin` / `superadmin`.

## Tests
```bash
set -a && . ./.env && set +a
pytest tests/unit -q                 # expect 59 passed
# Integration needs a LIVE Core running first:
export AURORA_INTEGRATION_BASE_URL=http://127.0.0.1:8000
pytest tests/integration -m integration -q   # expect 1 passed
```
Tip: tests derive paths from `__file__` (REPO_ROOT). Ephemeral artifacts land under repo-root `.testdata/` / `.agent-cache/` (gitignored).

## Dashboard e2e flow (proves the whole pipeline)
1. `/login` → password `superadmin` (username prefilled) → redirects to `/dashboard`; superadmin-only Admin/Backup tabs appear.
2. **Operations** tab → **Create random task** button (`#debug-enqueue`, superadmin-only). It enqueues an `echo` job with `required_tags=["default"]` via `POST /superadmin/debug/enqueue-random`.
3. With an agent running (tag `default`), the job goes queued → running → **completed**. Verify: "Task status split" donut turns green, "Latest logs" shows `[completed] JOB_... : slept=N` (or echo output).
   - ~12% of random rolls produce a `fail` job by design — click again to get an echo/sleep job for a clean completion demo.
   - If a job stays `queued`, no agent with the matching tag is consuming — start `python -m aurora_agent.worker`.

## Gotchas
- The exec/shell working directory can reset between calls; use absolute paths or re-`cd`.
- Cloned repo lives at `<repos_dir>/project-aurora` (or `/home/ubuntu/project-aurora`).
- The dashboard agent display name is auto-generated (e.g. "South Harbor 93"); it's still the local worker. Stale agents show `offline`.

## Devin Secrets Needed
- None for local dev. Dev tokens/creds come from `.env.example` (`AURORA_ADMIN_TOKEN`, `AURORA_BOOTSTRAP_TOKEN`, superadmin/superadmin). Production overrides via `AURORA_*` env vars; startup rejects default creds/weak tokens when `deployment_env=production`.
