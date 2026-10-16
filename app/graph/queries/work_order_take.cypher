MATCH (w:WorkOrder {id: $id})
WHERE w.status = 'open'
SET w.status = 'in_progress', w.assigned_to = $by, w.taken_at = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'work_order', subject: w.id, actor: $by, role: $role,
                     from_status: 'open', to_status: 'in_progress', reason: 'taken', detail_json: '{}',
                     source: 'system'})-[:OF]->(w)
RETURN w.id AS id
