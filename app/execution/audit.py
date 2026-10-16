"""Audit records that are not a decision state change (autonomy widened, break-glass, work orders, problems)."""

import json

from app import clock, ids
from app.graph.client import TenantGraph, rows


def write(tg: TenantGraph, subject: str, *, kind: str, actor: str, role: str, frm: str | None, to: str | None,
          reason: str, detail: dict | None = None) -> str | None:
    """Attach an AuditEvent to the decision, work order or problem with id `subject`."""
    aid = ids.audit_id()
    out = rows(tg.write("audit_write", {
        "subject": subject, "audit": aid, "ts": clock.now(), "seq": clock.next_ns(), "kind": kind, "actor": actor,
        "role": role, "from": frm, "to": to, "reason": reason,
        "detail": json.dumps(detail or {}, sort_keys=True, default=str),
    }))
    return aid if out else None


def for_subject(tg: TenantGraph, subject: str) -> list[dict]:
    out = rows(tg.read("audit_for_subject", {"id": subject}))
    for r in out:
        r["detail"] = json.loads(r.pop("detail_json") or "{}")
    return out
