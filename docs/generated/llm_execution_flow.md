# LLM Execution Flow

## Summary

This graph describes the Aurora LLM plugin flow. The core prototype uses a mock provider and command metadata retrieval. Ollama local provider support is available in beta, and a read-only allowlisted runtime path exists for health checks.

```mermaid
sequenceDiagram
  participant User as User / Operator
  participant Core as Aurora Core
  participant Agent as Aurora Agent
  participant Plugin as llm_plugin subprocess
  participant Docs as plugins/shared_assets/knowledge/cmd
  participant Provider as mock provider

  User->>Core: POST /jobs with llm_plugin payload
  Core->>Core: Persist Job queued
  Core-->>Agent: Lease job via /agents/jobs/next

  Agent->>Core: GET plugin manifest/download if needed
  Agent->>Plugin: Run subprocess with AURORA_JOB_PAYLOAD

  Plugin->>Plugin: Parse user query and mode
  Plugin->>Core: checkpoint input_received
  Plugin->>Docs: Load command metadata files
  Plugin->>Core: checkpoint metadata_loaded
  Plugin->>Plugin: Score command metadata by keywords/tags
  Plugin->>Core: checkpoint retrieval_completed
  Plugin->>Provider: Generate mock structured answer
  Provider-->>Plugin: Mock answer + usage metadata
  Plugin->>Core: checkpoint provider_response_generated
  Plugin-->>Agent: stdout/result JSON
  Agent->>Core: POST checkpoint result_ready if trace file exists
  Agent->>Core: POST /executions/{id}/result
```

## Invariants

- Core schedules and observes; it does not call LLM providers.
- Agent executes plugin subprocesses; it does not read Core DB internals.
- Prototype provider is mock and has zero cost.
- Work trace is exposed through checkpoints, not hidden reasoning.
- Command metadata retrieval is local and deterministic for prototype.

## Risk Controls

- No destructive command execution through the LLM runtime path.
- Read-only runtime commands are limited to an explicit allowlist.
- Runtime execution is disabled by default and must be feature-flagged.
- No external provider dependency in prototype.
- No vector database in prototype.
- Provider adapters stay plugin-local.
- Raw prompt and secrets are not stored by default.

## Runtime Beta Flow

```mermaid
flowchart TD
  PluginOut[llm_plugin output] --> Worker[Agent Worker]
  Worker --> PlanCheck{Approved plan?}
  PlanCheck -->|No| Reject[Skip runtime command]
  PlanCheck -->|Yes| Allowlist{Command in allowlist?}
  Allowlist -->|No| Reject
  Allowlist -->|Yes| HealthCall[Call read-only core health endpoint]
  HealthCall --> CoreHealth[Aurora Core /health or /health/ready]
  Worker --> Audit[POST /agents/runtime/audit]
  Audit --> CoreAudit[Core audit_logs table]
  CoreHealth --> RuntimeResult[Runtime result in job metrics]
```

Current allowlist:

- `health.ready`
- `health.live`
- `dashboard.overview`

## Future Command Execution Flow

```mermaid
flowchart TD
  Intent[User Intent] --> Retrieve[Retrieve Command Metadata]
  Retrieve --> Select[Select Allowlisted Command]
  Select --> Validate[Validate Payload + Role + Risk]
  Validate --> Confirm{Requires Confirmation?}
  Confirm -->|Yes| Token[Validate Confirmation Token]
  Confirm -->|No| Execute[Execute Allowlisted Command]
  Token --> Execute
  Execute --> Audit[Audit Result]
  Audit --> Result[Structured Result]
  Validate -->|Invalid| Reject[Reject With Explanation]
```

Execution must remain metadata-driven and audited. Free-form generated shell text must not be executed.

## Beta Extension

```mermaid
flowchart LR
  Plugin[llm_plugin] --> ProviderAdapter[Provider Adapter]
  ProviderAdapter --> Mock[mock]
  ProviderAdapter --> Ollama[ollama_local]
  Ollama --> LocalModel[Local Model Runtime]
```

Beta adds `ollama_local` without changing Aurora Core scheduling behavior.
