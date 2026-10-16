// A helper finishes a step: done (optionally passing work on), waiting for a decision to change, or failed.
// The next steps and the HANDED_OFF_TO links are written in the same query.
MATCH (t:Task {id: $id})-[:FOR]->(i:Incident)
WHERE t.status = 'claimed' AND t.owner = $agent
SET t.status = $status, t.result_json = $result, t.finished_at = $ts, t.wait_decision = $wait_decision,
    t.wait_seen_status = $wait_seen_status, t.lease_expires = null
FOREACH (n IN $next |
  CREATE (nt:Task {id: n.id, kind: n.kind, status: 'open', payload: n.payload, created_at: $ts, created_by: $agent,
                   attempts: 0, source: 'system'}),
         (nt)-[:FOR]->(i), (t)-[:HANDED_OFF_TO]->(nt))
RETURN t.id AS id
