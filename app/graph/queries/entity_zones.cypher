UNWIND $ids AS eid
MATCH (n:Entity {id: eid})
OPTIONAL MATCH (n)-[:LOCATED_IN|ROUTED_THROUGH|IN_ZONE]->(z:Zone)
RETURN n.id AS id, CASE WHEN 'Zone' IN labels(n) THEN n.id ELSE z.id END AS zone
