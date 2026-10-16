// Evidence links: sensors, meters, assets and the policy (Entity) plus reports.
MATCH (d:Decision {id: $id})
UNWIND $ids AS eid
MATCH (e) WHERE (e:Entity OR e:Report) AND e.id = eid
MERGE (d)-[:JUSTIFIED_BY]->(e)
RETURN count(e) AS n
