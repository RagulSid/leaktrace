MATCH (a:AuditEvent)-[:OF]->(:Decision {id: $id})
RETURN a.seq AS seq, a.ts AS ts, a.kind AS kind, a.subject AS subject, a.actor AS actor, a.role AS role,
       a.from_status AS from_status, a.to_status AS to_status, a.reason AS reason, a.detail_json AS detail_json
ORDER BY seq
