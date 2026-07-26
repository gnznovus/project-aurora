---
name: health.ready
method: GET
endpoint: /health/ready
auth: none
tags:
  - health
  - readiness
executable: true
execution_kind: aurora_api
---

# Health Readiness

Check bounded readiness for database, queue, schema guard, and scheduler state.
