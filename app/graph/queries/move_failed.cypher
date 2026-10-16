// A worker reports that a valve move failed: the step fails, every later step is cancelled, the decision
// fails (or, during an undo, rollback_failed). A valve reported stuck becomes an active "stuck" Fact about
// it, so the next plan treats it as unusable. One atomic query.
MATCH (t:Task {id: $task, kind: 'valve_move'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)
WHERE t.status = 'claimed' AND t.owner = $worker AND t.idem_key = $key AND d.status = $phase_status
MATCH (v:Valve) WHERE v.id = t.valve
SET t.status = 'failed', t.done_at = $ts, t.observed = $observed, t.failure = $reason,
    d.status = $final_status, d.status_ts = $ts, d.outcome = 'failed', x.failed_at = $ts
CREATE (:AuditEvent {id: $audit_task, ts: $ts, seq: $seq, kind: 'task', subject: t.id, actor: $worker, role: $role,
                     from_status: 'claimed', to_status: 'failed', reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
CREATE (:AuditEvent {id: $audit_decision, ts: $ts, seq: $seq2, kind: 'decision', subject: d.id, actor: $worker,
                     role: $role, from_status: $phase_status, to_status: $final_status,
                     reason: 'move_failed: ' + v.id + ' ' + $reason, detail_json: $detail, source: 'system'})-[:OF]->(d)
WITH t, x, d, v
CALL { WITH x
  MATCH (p:Task)-[:PART_OF]->(x) WHERE p.status = 'pending'
  SET p.status = 'cancelled'
  RETURN count(p) AS cancelled }
FOREACH (_ IN CASE WHEN $reason = 'stuck' THEN [1] ELSE [] END |
  CREATE (f:Fact {id: $fact, kind: 'stuck', status: 'active', statement: $statement, confidence: $fact_confidence,
                  valid_from: $ts, last_confirmed_at: $ts, source: 'field'})-[:ABOUT]->(v), (f)-[:EVIDENCED_BY]->(t))
RETURN d.status AS status, cancelled
