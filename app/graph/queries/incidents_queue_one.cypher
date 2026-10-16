MATCH (i:Incident {id: $id})
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision) WHERE d.status <> 'superseded'
       WITH d ORDER BY d.ts DESC LIMIT 1 RETURN d }
RETURN d.id AS decision
