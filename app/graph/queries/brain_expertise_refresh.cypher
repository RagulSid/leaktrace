// Who knows what: EXPERT_IN from the work people did (tickets on each asset), with score and basis.
MATCH (p:Person)-[:PERFORMED]->(t:Ticket)-[:ON]->(a)
WITH p, a, count(t) AS jobs, max(coalesce(t.closed_at, t.opened_at)) AS last
MERGE (p)-[e:EXPERT_IN]->(a)
SET e.score = jobs, e.basis = 'tickets', e.last = last
RETURN count(e) AS n
