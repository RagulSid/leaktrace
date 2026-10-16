// A person closes a problem that was fixed outside a verified plan (for example by hand).
MATCH (i:Incident {id: $id})
WHERE i.status = 'open'
SET i.status = 'closed', i.closed_at = $ts, i.closed_by = $by, i.close_reason = $reason
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'incident', subject: i.id, actor: $by, role: $role,
                     from_status: 'open', to_status: 'closed', reason: $reason, detail_json: '{}', source: 'system'})-[:OF]->(i)
RETURN i.id AS id
