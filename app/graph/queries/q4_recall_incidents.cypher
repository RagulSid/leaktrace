// Q4 Memory: for each asset in an incident, earlier incidents on the same asset with their decisions,
// and active facts about the asset. CALL subqueries keep each OPTIONAL MATCH out of an aggregated
// scope (see the note in q1_find_suspects.cypher).
MATCH (cur:Incident {id: $incident})-[:INVOLVED]->(a)
CALL {
  WITH cur, a
  OPTIONAL MATCH (past:Incident)-[:INVOLVED]->(a)
  WHERE past.id <> cur.id
  OPTIONAL MATCH (past)-[:DECIDED]->(d:Decision)
  RETURN collect(DISTINCT CASE WHEN past IS NULL THEN NULL ELSE {incident: past.id, decision: d.id, outcome: d.outcome} END) AS history
}
CALL {
  WITH a
  OPTIONAL MATCH (f:Fact {status: 'active'})-[:ABOUT]->(a)
  RETURN collect(DISTINCT f.statement) AS facts
}
RETURN a.id AS asset, history, facts
ORDER BY asset
