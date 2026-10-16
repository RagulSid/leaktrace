// A field worker picks up the next open valve move. Only the next step of a plan is ever open, so the
// moves happen in order. One conditional write: two workers can never hold the same step.
MATCH (t:Task {kind: 'valve_move', status: 'open'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)
WHERE t.attempts < $max_attempts AND d.status IN ['executing', 'rolling_back']
WITH t, x, d
ORDER BY t.created_at, t.phase, t.seq
LIMIT 1
SET t.status = 'claimed', t.owner = $worker, t.lease_expires = $until, t.attempts = t.attempts + 1, t.claimed_at = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'task', subject: t.id, actor: $worker, role: $role,
                     from_status: 'open', to_status: 'claimed', reason: 'attempt ' + toString(t.attempts),
                     detail_json: '{}', source: 'system'})-[:OF]->(d)
RETURN t.id AS id, t.phase AS phase, t.seq AS seq, t.valve AS valve, t.target AS target,
       t.idem_key AS idempotency_key, t.lease_expires AS lease_expires, t.attempts AS attempts,
       x.id AS execution, d.id AS decision
