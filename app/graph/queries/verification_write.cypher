// verifying -> verified | failed, with the Verification node (every check and its numbers) and the audit
// record. A verified fix closes the problem (status 'resolved'), so a new alarm opens a new problem.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $decision})<-[:IMPLEMENTS]-(x:Execution)
WHERE d.status = 'verifying'
SET d.status = $to, d.status_ts = $ts, d.outcome = $to, x.verified_at = $ts,
    i.status = CASE WHEN $passed THEN 'resolved' ELSE i.status END,
    i.closed_at = CASE WHEN $passed THEN $ts ELSE i.closed_at END,
    i.closed_by = CASE WHEN $passed THEN d.id ELSE i.closed_by END
CREATE (vf:Verification {id: $verification, ts: $ts, passed: $passed, failed_checks: $failed, checks_json: $checks_json,
                         by: $actor, source: 'system'})-[:VERIFIES]->(d)
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                     from_status: 'verifying', to_status: $to, reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
RETURN vf.id AS verification, i.id AS incident, i.status AS incident_status
