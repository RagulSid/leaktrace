MATCH (i:Incident {id: $incident})
UNWIND $ids AS eid
MATCH (n:Entity {id: eid})
MERGE (i)-[:INVOLVED]->(n)
RETURN count(n) AS n
