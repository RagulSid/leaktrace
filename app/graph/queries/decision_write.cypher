MATCH (i:Incident {id: $incident})
CREATE (d:Decision {id: $id, kind: $kind, ts: $ts, actor: $actor, suspect: $suspect,
                    confidence: $confidence, confidence_level: $confidence_level,
                    signs_agree: $signs_agree, signs_total: $signs_total,
                    authority_level: $authority_level, failed_conditions: $failed_conditions,
                    summary: $summary, evidence_paths: $evidence_paths, explain_json: $explain_json,
                    status: $status, status_ts: $ts, requested_by: $requested_by, zone: $zone, policy: $policy,
                    fingerprint: $fingerprint, snapshot_json: $snapshot_json,
                    outcome: 'pending', source: $source})
CREATE (i)-[:DECIDED]->(d)
WITH d
OPTIONAL MATCH (c:Option {id: $chosen})
FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | CREATE (d)-[:CHOSE {role: 'chosen'}]->(c))
WITH d
OPTIONAL MATCH (f:Option {id: $fallback})
FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | CREATE (d)-[:CHOSE {role: 'fallback'}]->(f))
RETURN d.id AS id
