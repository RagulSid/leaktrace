// A helper picks up the oldest open step of the kinds it handles. One conditional write.
MATCH (t:Task {status: 'open'})-[:FOR]->(i:Incident)
WHERE t.kind IN $kinds
WITH t, i
ORDER BY t.created_at, t.id
LIMIT 1
SET t.status = 'claimed', t.owner = $agent, t.lease_expires = $until, t.attempts = t.attempts + 1, t.claimed_at = $ts
MERGE (a:Agent {id: $agent})
ON CREATE SET a.role = $role, a.source = 'system'
SET a.last_seen = $ts, a.status = 'working', a.chooser = $chooser, a.pid = $pid
MERGE (t)-[:CLAIMED_BY]->(a)
RETURN t.id AS id, t.kind AS kind, t.payload AS payload, i.id AS incident, t.attempts AS attempts
