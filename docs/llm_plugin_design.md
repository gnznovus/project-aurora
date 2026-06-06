# Aurora LLM Plugin Design

## Summary

The `llm_plugin` is a subprocess plugin that accepts a user request, retrieves relevant command metadata, generates a structured response through a provider adapter, and writes work-trace checkpoints during execution.

The prototype provider is `mock`; Ollama local support is deferred to beta.

## Plugin Input Contract

```json
{
  "schema_version": "v1",
  "provider": "mock",
  "query": "How do I restore a backup safely?",
  "mode": "answer",
  "execution_policy": "suggest_only",
  "max_results": 5,
  "include_command_examples": true,
  "trace_enabled": true
}
```

Fields:
- `schema_version`: contract version, currently `v1`
- `provider`: `mock` for prototype, `ollama_local` for beta
- `query`: user intent or question
- `mode`: `answer`, `plan`, or `command_suggest`
- `execution_policy`: `suggest_only` for prototype; future values may include `plan_only` and `allowlisted_execute`
- `max_results`: maximum command metadata matches
- `include_command_examples`: include command examples when available
- `trace_enabled`: write work-trace checkpoints

## Command Metadata Format

Shared command metadata should live under `plugins/shared_assets/knowledge/cmd/`.
Plugin-local LLM knowledge should live under `plugins/LLM/knowledge/cmd/`.

Suggested file shape:

```markdown
---
name: backup.restore
method: POST
endpoint: /superadmin/backups/{backup_id}/restore
auth: superadmin_session
tags:
  - backup
  - restore
  - destructive
---

# Restore Backup

Safely dry-run or apply a backup restore.

## Payload Example

```json
{
  "confirm": "BKP_...",
  "confirm_token": "cfm_..."
}
```
```

Required metadata:
- `name`
- `method`
- `endpoint`
- `auth`
- `tags`

Optional metadata:
- `risk_level`
- `requires_confirmation`
- `executable`
- `execution_kind`
- `payload_schema`
- `examples`

## Retrieval Rules

Prototype retrieval is keyword/tag based:
- tokenize query
- score metadata `name`, `endpoint`, `tags`, heading text
- return top `max_results`
- include confidence score

No embeddings are required for prototype.

## Provider Adapter Boundary

Provider adapter interface:

```json
{
  "provider": "mock",
  "model": "mock-llm-v1",
  "input_summary": "...",
  "output": {
    "answer": "...",
    "commands": []
  },
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0
  }
}
```

Rules:
- Provider code lives inside plugin runtime.
- Core never imports provider SDKs.
- Agent never accesses provider credentials directly except via plugin environment/config.
- Mock provider remains default for tests.

## Output Contract

```json
{
  "schema_version": "v1",
  "provider": "mock",
  "status": "completed",
  "answer": "Use restore dry-run first, then issue a confirmation token before restore apply.",
  "matched_commands": [
    {
      "name": "backup.restore",
      "endpoint": "/superadmin/backups/{backup_id}/restore",
      "method": "POST",
      "confidence": 0.91
    }
  ],
  "work_trace": [
    {
      "stage": "retrieval",
      "message": "Matched backup restore command metadata",
      "confidence": 0.91
    }
  ],
  "usage": {
    "provider": "mock",
    "model": "mock-llm-v1",
    "estimated_cost_usd": 0
  }
}
```

## Observability

The plugin should checkpoint these stages:
- `input_received`
- `metadata_loaded`
- `retrieval_completed`
- `provider_response_generated`
- `result_ready`

Each checkpoint should include:
- `stage`
- `message`
- `selected_commands`
- `confidence`
- `provider`

## Safety Rules

- Do not execute destructive actions automatically.
- Do not execute runtime commands in prototype.
- Do not store raw secrets.
- Do not expose hidden chain-of-thought.
- Prefer command suggestions and plans over direct action execution.
- Redact sensitive user payloads from checkpoints unless explicitly enabled.

## Runtime Command Execution Plan

Runtime command execution is a planned future capability. It must be implemented as an explicit allowlisted path, not as arbitrary shell execution.

Execution policy phases:

- `suggest_only`: return relevant commands and explanation; no execution.
- `plan_only`: build validated command plan; no execution.
- `allowlisted_execute`: execute only commands marked executable in metadata.

Required metadata for executable commands:

```yaml
executable: true
execution_kind: aurora_api
risk_level: destructive
requires_confirmation: true
required_role: superadmin
```

Execution requirements:

- The selected command must come from parsed metadata, not generated text.
- Payload must validate against metadata schema.
- Destructive commands must require a confirmation token.
- Execution must emit checkpoints for `plan_validated`, `permission_checked`, `execution_started`, and `execution_completed`.
- Audit logs must include actor, request_id, command name, endpoint, risk level, and result status.
- Output must be size bounded and redacted before storing in result payload.

Prototype implementation should leave this as documented design only.

## Test Strategy

Prototype tests should cover:
- command metadata parsing
- keyword/tag retrieval
- mock provider response shape
- work-trace checkpoint output
- no-cost usage metadata
