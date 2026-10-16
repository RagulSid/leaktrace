MATCH (t:Team)-[:OWNS]->(w:Workload)
WHERE w.id IN $ids
RETURN w.id AS workload, collect(t.id) AS owners
