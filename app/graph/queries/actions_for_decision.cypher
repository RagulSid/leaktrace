MATCH (a:Action)-[:IMPLEMENTS]->(:Decision {id: $id})
OPTIONAL MATCH (a)-[:AUTHORIZED_BY]->(auth)
RETURN a.id AS id, a.phase AS phase, a.valve AS valve, a.from_state AS from_state, a.to_state AS to_state,
       a.by AS by, a.ts AS ts, a.idem_key AS idempotency_key, auth.id AS authorized_by
ORDER BY a.seq
