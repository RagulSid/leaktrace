MATCH (w:WorkOrder {id: $id})
CALL { WITH w OPTIONAL MATCH (w)-[:FOR]->(i:Incident) RETURN i.id AS incident }
RETURN properties(w) AS work_order, incident
