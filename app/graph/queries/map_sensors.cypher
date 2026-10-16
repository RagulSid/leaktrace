MATCH (s:Sensor)-[:MONITORS]->(x)
RETURN s.id AS id, s.kind AS kind, s.state AS state, x.id AS watches
ORDER BY id
