MATCH (w:WorkOrder {id: $id})-[:FOR]->(i:Incident)
RETURN properties(w) AS work_order, i.id AS incident
