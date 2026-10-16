// Field confirmation of one step by the crew member who holds the job.
MATCH (w:WorkOrder {id: $id})
WHERE w.status = 'in_progress' AND w.assigned_to = $by AND $step IN w.steps AND NOT $step IN w.confirmed
SET w.confirmed = w.confirmed + [$step]
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'work_order', subject: w.id, actor: $by, role: $role,
                     from_status: 'in_progress', to_status: 'in_progress', reason: 'confirmed: ' + $step,
                     detail_json: $detail, source: 'system'})-[:OF]->(w)
RETURN w.id AS id, w.confirmed AS confirmed
