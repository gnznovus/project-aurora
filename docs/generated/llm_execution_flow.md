# LLM Execution Flow

## Summary

This graph describes the planned Aurora LLM plugin prototype. The first version uses a mock provider and command metadata retrieval only. Ollama local provider support is reserved for beta.

```mermaid
sequenceDiagram
  participant User as User / Operator
  participant Core as Aurora Core
  participant Agent as Aurora Agent
  participant Plugin as llm_plugin subprocess
  participant Docs as knowledge/commands
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

- No destructive command execution in prototype.
- No runtime command execution in prototype.
- No external provider dependency in prototype.
- No vector database in prototype.
- Provider adapters stay plugin-local.
- Raw prompt and secrets are not stored by default.

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

Execution must be metadata-driven and audited. Free-form generated shell text must not be executed.

## Beta Extension

```mermaid
flowchart LR
  Plugin[llm_plugin] --> ProviderAdapter[Provider Adapter]
  ProviderAdapter --> Mock[mock]
  ProviderAdapter --> Ollama[ollama_local]
  Ollama --> LocalModel[Local Model Runtime]
```

Beta adds `ollama_local` without changing Aurora Core scheduling behavior.
