// A person's saved conversation about one problem (or about nothing in particular), oldest first.
MATCH (c:Conversation {id: $conv})-[:WITH]->(u:User)
WHERE u.id = $user
MATCH (m:Message)-[:IN]->(c)
RETURN m.id AS id, m.role AS role, m.text AS text, m.ts AS ts, m.cites AS cites, m.known AS known,
       m.phrased_by AS phrased_by, m.fallback AS fallback, m.offer AS offer
ORDER BY m.ts, m.seq
