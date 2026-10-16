// A worker reports a valve move as done, in one atomic query: the step is marked done, the valve state and
// the capacities of the links it controls are set, an Action is recorded (linked to the decision, the valve
// and what authorised it), and the next step opens; after the last step the decision moves on
// ($final_status: verifying after the plan, rolled_back after an undo). Zero rows: the report is refused.
MATCH (t:Task {id: $task, kind: 'valve_move'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)
WHERE t.status = 'claimed' AND t.owner = $worker AND t.idem_key = $key AND d.status = $phase_status
MATCH (v:Valve) WHERE v.id = t.valve
WITH t, x, d, v
// The link update runs before any value is projected: a write CALL after a projected alias and a SET
// fails on this FalkorDB build ("Variable r not found"; regression test in tests/test_falkordb_quirks.py).
CALL { WITH t
  UNWIND range(0, size(t.edge_ids) - 1) AS k
  MATCH ()-[r:FLOWS_TO {id: t.edge_ids[k]}]->()
  SET r.cap_base = t.edge_caps[k]
  RETURN count(r) AS edges }
WITH t, x, d, v, edges, v.state AS before
SET t.status = 'done', t.done_at = $ts, t.observed = $observed, v.state = t.target, v.state_ts = $ts
CREATE (a:Action {id: $action, phase: t.phase, valve: v.id, from_state: before, to_state: t.target, ts: $ts, seq: $seq,
                  zone: x.zone, idem_key: t.idem_key, by: $worker, adapter: x.adapter, simulated: x.simulated,
                  source: 'system'})
CREATE (a)-[:IMPLEMENTS]->(d), (a)-[:OPERATES]->(v), (a)-[:PART_OF]->(x)
CREATE (:AuditEvent {id: $audit_task, ts: $ts, seq: $seq, kind: 'task', subject: t.id, actor: $worker, role: $role,
                     from_status: 'claimed', to_status: 'done', reason: t.phase + ': ' + t.target + ' ' + v.id,
                     detail_json: $detail, source: 'system'})-[:OF]->(d)
WITH t, x, d, a, edges
OPTIONAL MATCH (auth) WHERE (auth:AuthorityPolicy OR auth:Approval) AND auth.id = x.authorized_by
FOREACH (_ IN CASE WHEN auth IS NULL THEN [] ELSE [1] END | CREATE (a)-[:AUTHORIZED_BY]->(auth))
WITH t, x, d, edges
OPTIONAL MATCH (n:Task)-[:PART_OF]->(x)
WHERE n.phase = t.phase AND n.seq = t.seq + 1 AND n.status = 'pending'
FOREACH (_ IN CASE WHEN n IS NULL THEN [] ELSE [1] END | SET n.status = 'open', n.opened_at = $ts)
FOREACH (_ IN CASE WHEN n IS NULL THEN [1] ELSE [] END |
  SET d.status = $final_status, d.status_ts = $ts, x.phase_done_at = $ts,
      x.verifying_since = CASE WHEN $final_status = 'verifying' THEN $ts ELSE x.verifying_since END,
      d.outcome = CASE WHEN $final_status = 'rolled_back' THEN 'rolled_back' ELSE d.outcome END
  CREATE (:AuditEvent {id: $audit_decision, ts: $ts, seq: $seq2, kind: 'decision', subject: d.id, actor: $worker,
                       role: $role, from_status: $phase_status, to_status: $final_status, reason: $final_reason,
                       detail_json: '{}', source: 'system'})-[:OF]->(d))
RETURN n.id AS next_task, d.status AS status, edges
