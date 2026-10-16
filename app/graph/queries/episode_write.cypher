CREATE (e:Episode {id: $id, kind: $kind, ts: $ts, actor: $actor, tool: $tool, args_json: $args_json,
                   summary: $summary, ms: $ms, ok: $ok, source: 'system'})
WITH e
OPTIONAL MATCH (i:Incident {id: $incident})
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (e)-[:OF]->(i))
RETURN e.id AS id
