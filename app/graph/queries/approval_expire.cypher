// An approval that ran out puts the decision back to proposed (someone has to approve again).
MATCH (ap:Approval {id: $approval, status: 'active'})-[:APPROVES]->(d:Decision)
WHERE d.status = 'approved' AND ap.expires_at < $now
SET ap.status = 'expired', d.status = 'proposed', d.status_ts = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: 'system', role: 'system',
                     from_status: 'approved', to_status: 'proposed', reason: 'approval_expired',
                     detail_json: $detail, source: 'system'})-[:OF]->(d)
RETURN d.id AS decision
