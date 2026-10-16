MATCH (i:Incident {id: $id})
SET i.severity = $severity
RETURN i.id AS id
