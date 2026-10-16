MATCH (e:Episode)-[:OF]->(:Incident {id: $incident})
RETURN e.ts AS ts, e.actor AS actor, e.kind AS kind, e.tool AS tool, e.summary AS summary, e.ok AS ok, e.ms AS ms
ORDER BY ts
