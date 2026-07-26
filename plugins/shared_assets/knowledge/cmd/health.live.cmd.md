---
name: health.live
method: GET
endpoint: /health
auth: none
tags:
  - health
  - liveliness
executable: true
execution_kind: aurora_api
---

# Health Liveness

Check the shallow liveness endpoint for the Aurora core service.
