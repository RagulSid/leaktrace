// Auto mode was paused after the decision was committed: "handled automatically" becomes "needs your OK".
MATCH (d:Decision {id: $id})
WHERE d.status = 'proposed' AND d.authority_level = 'L2'
SET d.authority_level = 'L3', d.failed_conditions = d.failed_conditions + [$condition], d.downgraded_at = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'authority', subject: d.id, actor: $actor, role: $role,
                     from_status: 'L2', to_status: 'L3', reason: $reason, detail_json: $detail, source: 'system'})-[:OF]->(d)
RETURN d.id AS id
