// Who knows an asset: people with EXPERT_IN (from the tickets they did), most jobs first.
MATCH (p:Person)-[e:EXPERT_IN]->(a:Entity)
WHERE a.id IN $ids
CALL { WITH p, a OPTIONAL MATCH (p)-[:PERFORMED]->(t:Ticket)-[:ON]->(a) RETURN collect(t.id) AS tickets }
CALL { WITH p OPTIONAL MATCH (p)-[:MEMBER_OF]->(tm:Team) RETURN collect(tm.name) AS teams }
RETURN p.id AS id, p.name AS name, p.title AS title, a.id AS about, a.name AS about_name, e.score AS jobs,
       e.last AS last, e.basis AS basis, tickets, teams
ORDER BY jobs DESC, last DESC
