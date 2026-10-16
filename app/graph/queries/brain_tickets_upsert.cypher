// Maintenance tickets: on one asset, done by one person.
UNWIND $rows AS row
MERGE (t:Ticket {id: row.id})
SET t.title = row.title, t.text = row.text, t.problem_code = row.problem_code, t.status = row.status,
    t.opened_at = row.opened_at, t.closed_at = row.closed_at, t.source = $source
WITH t, row
MATCH (a:Entity) WHERE a.id = row.asset
MERGE (t)-[:ON]->(a)
WITH t, row
OPTIONAL MATCH (p:Person) WHERE p.id = row.performed_by
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:PERFORMED]->(t))
RETURN count(t) AS n
