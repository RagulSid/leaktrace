// A step was abandoned (its last lease ran out): the execution fails and every later step is cancelled.
MATCH (x:Execution)-[:IMPLEMENTS]->(d:Decision {id: $decision})
WHERE d.status = $phase_status
SET d.status = $final_status, d.status_ts = $ts, d.outcome = 'failed', x.failed_at = $ts
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: 'system', role: 'system',
                     from_status: $phase_status, to_status: $final_status, reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
WITH x, d
CALL { WITH x
  MATCH (p:Task)-[:PART_OF]->(x) WHERE p.status IN ['pending', 'open']
  SET p.status = 'cancelled'
  RETURN count(p) AS cancelled }
RETURN d.status AS status, cancelled
