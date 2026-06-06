---
name: jobs.enqueue
method: POST
endpoint: /jobs
auth: admin_token
tags:
  - job
  - enqueue
  - idempotent
executable: false
execution_kind: aurora_api
---

# Enqueue Job

Create a queued job for a registered plugin version.
