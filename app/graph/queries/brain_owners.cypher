// Who owns an asset: teams that own it, teams owning jobs that run on it, and the chart that says so.
MATCH (a:Entity) WHERE a.id IN $ids
CALL { WITH a OPTIONAL MATCH (t:Team)-[:OWNS]->(a) RETURN collect({id: t.id, name: t.name}) AS teams }
CALL { WITH a OPTIONAL MATCH (w:Workload)-[:RUNS_ON]->(a) OPTIONAL MATCH (t2:Team)-[:OWNS]->(w)
       RETURN collect({id: t2.id, name: t2.name, workload: w.id, workload_name: w.name}) AS via_jobs }
CALL { WITH a OPTIONAL MATCH (d:Document)-[:MENTIONS]->(a) WHERE d.kind = 'org_chart' RETURN collect(d.id) AS charts }
RETURN a.id AS id, a.name AS name, teams, via_jobs, charts
