// verifying -> verified | failed, with the Verification node (every check and its numbers) and the audit record.
MATCH (x:Execution)-[:IMPLEMENTS]->(d:Decision {id: $decision})
WHERE d.status = 'verifying'
SET d.status = $to, d.status_ts = $ts, d.outcome = $to, x.verified_at = $ts
CREATE (vf:Verification {id: $verification, ts: $ts, passed: $passed, failed_checks: $failed, checks_json: $checks_json,
                         by: $actor, source: 'system'})-[:VERIFIES]->(d)
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                     from_status: 'verifying', to_status: $to, reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
RETURN vf.id AS verification
