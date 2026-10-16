MATCH (i:Incident {id: $incident})
CREATE (t:Task {id: $id, kind: $kind, status: 'open', payload: $payload, created_at: $ts, created_by: $actor,
                attempts: 0, source: 'system'})-[:FOR]->(i)
RETURN t.id AS id
