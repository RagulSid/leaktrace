// Save turns of a person's conversation with Ask LeakTrace, one conversation per person and problem.
MATCH (u:User) WHERE u.id = $user
MERGE (c:Conversation {id: $conv})
ON CREATE SET c.kind = 'ask', c.created_at = $ts, c.user = $user, c.incident = $incident, c.source = 'system'
MERGE (c)-[:WITH]->(u)
WITH c
OPTIONAL MATCH (i:Incident) WHERE i.id = $incident
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | MERGE (c)-[:ABOUT]->(i))
WITH c
UNWIND $messages AS m
CREATE (x:Message {id: m.id, role: m.role, text: m.text, ts: m.ts, seq: m.seq, cites: m.cites, known: m.known,
                   phrased_by: m.phrased_by, fallback: m.fallback, offer: m.offer})
CREATE (x)-[:IN]->(c)
RETURN count(x) AS n
