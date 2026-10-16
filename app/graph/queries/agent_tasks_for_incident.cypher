// The hand-off chain for one problem, read from the graph.
MATCH (t:Task)-[:FOR]->(:Incident {id: $incident})
WHERE t.kind IN $kinds
OPTIONAL MATCH (t)-[:CLAIMED_BY]->(a:Agent)
OPTIONAL MATCH (t)-[:HANDED_OFF_TO]->(n:Task)
RETURN t.id AS id, t.kind AS kind, t.status AS status, t.created_at AS created_at, t.attempts AS attempts,
       collect(DISTINCT a.id) AS agents, collect(DISTINCT n.id) AS handed_to, t.result_json AS result_json
ORDER BY created_at, id
