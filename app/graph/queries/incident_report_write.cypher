MATCH (i:Incident {id: $incident})
CREATE (r:IncidentReport {id: $id, ts: $ts, facts_json: $facts, prose: $prose, prose_by: $prose_by,
                          written_by: $actor, source: 'system'})-[:ABOUT]->(i)
RETURN r.id AS id
