MATCH (a:AuditEvent {kind: 'policy'})-[:OF]->(:AuthorityPolicy {id: $id})
RETURN a.ts AS ts, a.actor AS actor, a.reason AS reason, a.detail_json AS detail_json
ORDER BY a.seq DESC
LIMIT 20
