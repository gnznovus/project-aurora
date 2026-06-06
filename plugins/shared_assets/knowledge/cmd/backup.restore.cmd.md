---
name: backup.restore
method: POST
endpoint: /superadmin/backups/{backup_id}/restore
auth: superadmin_session
tags:
  - backup
  - restore
  - destructive
risk_level: destructive
requires_confirmation: true
executable: false
execution_kind: aurora_api
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
