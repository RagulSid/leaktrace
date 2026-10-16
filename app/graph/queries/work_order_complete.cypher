MATCH (w:WorkOrder {id: $id})
WHERE w.status = 'in_progress' AND w.assigned_to = $by AND all(s IN w.steps WHERE s IN w.confirmed)
SET w.status = 'done', w.done_at = $ts, w.findings = $findings
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'work_order', subject: w.id, actor: $by, role: $role,
                     from_status: 'in_progress', to_status: 'done', reason: 'completed', detail_json: $detail,
                     source: 'system'})-[:OF]->(w)
RETURN w.id AS id
