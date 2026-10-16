// People and the team each belongs to.
UNWIND $rows AS row
MERGE (p:Person {id: row.id})
SET p.name = row.name, p.title = row.title, p.source = $source
WITH p, row
MATCH (t:Team) WHERE t.id = row.team
MERGE (p)-[:MEMBER_OF]->(t)
RETURN count(p) AS n
