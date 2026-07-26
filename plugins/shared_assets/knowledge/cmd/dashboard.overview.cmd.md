---
name: dashboard.overview
method: GET
endpoint: /agents/runtime/overview
auth: agent_api_key
tags:
  - dashboard
  - runtime
  - summary
executable: true
execution_kind: aurora_api
---

# Runtime Overview

Return a read-only runtime summary for the current agent, including job and execution counters.
