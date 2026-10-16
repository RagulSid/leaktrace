MATCH (:Incident {id: $incident})-[:DECIDED]->(d:Decision)
WHERE d.status IN $statuses
RETURN d.id AS id, d.status AS status
ORDER BY d.ts
