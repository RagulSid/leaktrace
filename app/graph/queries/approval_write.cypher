// Approve: proposed -> approved, with the Approval node and its audit record, atomically.
MATCH (d:Decision {id: $id})
WHERE d.status = 'proposed'
SET d.status = 'approved', d.status_ts = $ts
CREATE (ap:Approval {id: $approval, by: $by, role: $role, ts: $ts, expires_at: $expires_at, ttl_s: $ttl_s,
                     note: $note, status: 'active', source: 'system'})-[:APPROVES]->(d)
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $by, role: $role,
                     from_status: 'proposed', to_status: 'approved', reason: $reason, detail_json: $detail, source: 'system'})-[:OF]->(d)
RETURN ap.id AS approval
