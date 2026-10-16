MATCH (i:Incident {status: 'open'})-[:INVOLVED]->(:Zone {id: $zone})
RETURN i.id AS id
ORDER BY i.opened_at
LIMIT 1
