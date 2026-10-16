// Leases that ran out: the step goes back to open for another worker, or is abandoned after the last
// allowed attempt (the execution then fails: nobody knows for sure whether that valve moved).
MATCH (t:Task {kind: 'valve_move', status: 'claimed'})-[:PART_OF]->(:Execution)-[:IMPLEMENTS]->(d:Decision)
WHERE t.lease_expires < $now
WITH t, d, t.owner AS lost, CASE WHEN t.attempts >= $max_attempts THEN 'abandoned' ELSE 'open' END AS next
SET t.status = next, t.owner = null, t.released_at = $now, t.lost_owner = lost
CREATE (:AuditEvent {id: 'AUD-' + t.id + '-L' + toString(t.attempts), ts: $now, seq: $seq, kind: 'task', subject: t.id,
                     actor: 'system', role: 'system', from_status: 'claimed', to_status: next,
                     reason: 'lease_expired (' + lost + ')', detail_json: '{}', source: 'system'})-[:OF]->(d)
RETURN t.id AS task, next AS status, d.id AS decision, t.phase AS phase
