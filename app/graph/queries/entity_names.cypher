UNWIND $ids AS eid
MATCH (n:Entity) WHERE n.id = eid
RETURN n.id AS id, n.name AS name
