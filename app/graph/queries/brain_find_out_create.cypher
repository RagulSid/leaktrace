// "Ask the field crew to find out": a job for the crew with the open question, on the asset if one was named.
OPTIONAL MATCH (i:Incident) WHERE i.id = $incident
OPTIONAL MATCH (a:Entity) WHERE a.id = $target
CREATE (w:WorkOrder {id: $id, kind: 'find_out', target: $target, status: 'open', steps: $steps, confirmed: [],
                     question: $question, created_at: $ts, created_by: $actor, source: 'system'})
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | CREATE (w)-[:FOR]->(i))
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | CREATE (w)-[:ON]->(a))
RETURN w.id AS id
