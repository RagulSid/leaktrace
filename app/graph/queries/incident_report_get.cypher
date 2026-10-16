MATCH (r:IncidentReport)-[:ABOUT]->(:Incident {id: $incident})
RETURN r.id AS id, r.ts AS ts, r.facts_json AS facts_json, r.prose AS prose, r.prose_by AS prose_by,
       r.written_by AS written_by
ORDER BY ts DESC
LIMIT 1
