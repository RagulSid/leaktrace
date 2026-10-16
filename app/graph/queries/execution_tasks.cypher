MATCH (t:Task)-[:PART_OF]->(:Execution {id: $execution})
RETURN t.id AS id, t.phase AS phase, t.seq AS seq, t.valve AS valve, t.target AS target,
       t.prior_state AS prior_state, t.status AS status, t.owner AS owner, t.attempts AS attempts,
       t.idem_key AS idempotency_key, t.failure AS failure, t.observed AS observed,
       t.edge_ids AS edge_ids, t.edge_caps AS edge_caps
ORDER BY phase, seq
