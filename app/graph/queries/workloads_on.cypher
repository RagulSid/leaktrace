UNWIND $ids AS cid
MATCH (w:Workload)-[:RUNS_ON]->(c:Consumer {id: cid})
OPTIONAL MATCH (t:Team)-[:OWNS]->(w)
RETURN c.id AS consumer, w.id AS workload, w.criticality AS criticality, w.migratable AS migratable,
       collect(t.id) AS owners
ORDER BY consumer, workload
