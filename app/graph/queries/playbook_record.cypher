// Count one finished decision for a playbook (plan pattern on a section). A decision is counted once.
MATCH (d:Decision {id: $decision})
MERGE (p:Playbook {key: $key})
ON CREATE SET p.id = $id, p.name = $name, p.segment = $segment, p.steps = $steps, p.success_count = 0,
              p.failure_count = 0, p.created_at = $ts, p.source = 'system'
WITH p, d
OPTIONAL MATCH (p)-[e:DERIVED_FROM]->(d)
WITH p, d, count(e) AS seen
FOREACH (_ IN CASE WHEN seen = 0 THEN [1] ELSE [] END |
  SET p.success_count = p.success_count + $s, p.failure_count = p.failure_count + $f, p.updated_at = $ts,
      p.last_outcome = $outcome
  CREATE (p)-[:DERIVED_FROM]->(d))
RETURN p.id AS id, p.success_count AS success_count, p.failure_count AS failure_count, seen = 0 AS counted
