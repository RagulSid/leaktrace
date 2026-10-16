// failed | verified -> rolling_back, with the undo steps (reverse order, each restoring the exact prior
// valve state and link capacities). With nothing to undo it goes straight on to rolled_back. One atomic query.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $decision})<-[:IMPLEMENTS]-(x:Execution)
WHERE d.status IN ['failed', 'verified']
WITH i, d, x, d.status AS prev
SET d.status = $final, d.status_ts = $ts, x.rollback_requested_by = $actor, x.rollback_at = $ts,
    d.outcome = CASE WHEN $final = 'rolled_back' THEN 'rolled_back' ELSE d.outcome END
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                     from_status: prev, to_status: 'rolling_back', reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(d)
FOREACH (_ IN CASE WHEN $final = 'rolled_back' THEN [1] ELSE [] END |
  CREATE (:AuditEvent {id: $audit2, ts: $ts, seq: $seq2, kind: 'decision', subject: d.id, actor: $actor, role: $role,
                       from_status: 'rolling_back', to_status: 'rolled_back', reason: 'nothing_to_undo',
                       detail_json: '{}', source: 'system'})-[:OF]->(d))
FOREACH (tk IN $tasks |
  CREATE (t:Task {id: tk.id, kind: 'valve_move', phase: tk.phase, seq: tk.seq, status: tk.status, valve: tk.valve,
                  target: tk.target, prior_state: tk.prior_state, edge_ids: tk.edge_ids, edge_caps: tk.edge_caps,
                  idem_key: tk.idem_key, attempts: 0, created_at: $ts, created_by: $actor, source: 'system'}),
         (t)-[:PART_OF]->(x), (t)-[:FOR]->(i))
RETURN d.status AS status, prev
