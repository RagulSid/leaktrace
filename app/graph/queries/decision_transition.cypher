// Compare-and-set on the decision status plus its audit record, in one atomic query.
// Zero rows back means the decision was not in any of the expected states: the transition is refused.
MATCH (d:Decision {id: $id})
WHERE d.status IN $from
WITH d, d.status AS prev
SET d.status = $to, d.status_ts = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                     from_status: prev, to_status: $to, reason: $reason, detail_json: $detail, source: 'system'})-[:OF]->(d)
RETURN prev
