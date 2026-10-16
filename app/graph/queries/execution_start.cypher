// approved -> executing, the Execution node and one ordered Task per valve move, atomically.
// Refused (zero rows) unless the decision is approved and every valve the plan moves is still in the
// state the plan was computed for.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $decision})
WHERE d.status = 'approved'
OPTIONAL MATCH (v:Valve) WHERE v.id IN $valve_ids
WITH i, d, collect(v) AS vs
WHERE size(vs) = size($valve_ids) AND all(v IN vs WHERE v.state = $prior[v.id])
SET d.status = 'executing', d.status_ts = $ts
CREATE (x:Execution {id: $execution, decision: d.id, incident: i.id, zone: $zone, started_at: $ts, started_by: $actor,
                     adapter: $adapter, simulated: $simulated, authorized_by: $authorized_by,
                     prior_json: $prior_json, expected_json: $expected_json, verify_window_s: $verify_window_s,
                     source: 'system'})-[:IMPLEMENTS]->(d)
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                     from_status: 'approved', to_status: 'executing', reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
WITH i, d, x
UNWIND $tasks AS tk
CREATE (t:Task {id: tk.id, kind: 'valve_move', phase: tk.phase, seq: tk.seq, status: tk.status, valve: tk.valve,
                target: tk.target, prior_state: tk.prior_state, edge_ids: tk.edge_ids, edge_caps: tk.edge_caps,
                idem_key: tk.idem_key, attempts: 0, created_at: $ts, created_by: $actor, source: 'system'})
CREATE (t)-[:PART_OF]->(x), (t)-[:FOR]->(i)
RETURN x.id AS execution, count(t) AS tasks
