from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aurora_core.services.models import IdempotencyRecord
from aurora_core.utils.timeutils import utc_now_naive


@dataclass
class IdempotencyLookupResult:
    replay: bool
    conflict: bool
    response_json: dict[str, Any] | None = None
    status_code: int = 200


def canonical_payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def lookup_record(db: Session, *, route: str, idem_key: str, payload_hash: str) -> IdempotencyLookupResult:
    now = utc_now_naive()
    row = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.route == route, IdempotencyRecord.idem_key == idem_key))
    if not row:
        return IdempotencyLookupResult(replay=False, conflict=False)

    if row.expires_at <= now:
        db.delete(row)
        db.commit()
        return IdempotencyLookupResult(replay=False, conflict=False)

    if row.payload_hash != payload_hash:
        return IdempotencyLookupResult(replay=False, conflict=True)

    return IdempotencyLookupResult(
        replay=True,
        conflict=False,
        response_json=dict(row.response_json or {}),
        status_code=row.status_code,
    )


def store_record(
    db: Session,
    *,
    route: str,
    idem_key: str,
    payload_hash: str,
    response_json: dict[str, Any],
    status_code: int,
    ttl_seconds: int,
) -> None:
    now = utc_now_naive()
    row = IdempotencyRecord(
        route=route,
        idem_key=idem_key,
        payload_hash=payload_hash,
        status_code=status_code,
        response_json=response_json,
        expires_at=now + timedelta(seconds=max(60, ttl_seconds)),
    )
    db.add(row)
    db.commit()
