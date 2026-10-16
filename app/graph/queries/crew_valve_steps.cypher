// Valve moves the field crew can see: open ones, and the ones this person holds.
MATCH (t:Task {kind: 'valve_move'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)<-[:DECIDED]-(i:Incident)
WHERE t.status = 'open' OR (t.status = 'claimed' AND t.owner = $user)
CALL { WITH d OPTIONAL MATCH (ap:Approval)-[:APPROVES]->(d) RETURN collect(ap.by) AS approvers }
RETURN t.id AS id, t.phase AS phase, t.seq AS seq, t.valve AS valve, t.target AS target, t.status AS status,
       t.owner AS owner, t.lease_expires AS lease_expires, t.idem_key AS idempotency_key, d.id AS decision,
       d.authority_level AS authority_level, i.id AS incident, approvers, x.verify_window_s AS check_window_s
ORDER BY t.created_at, t.seq
