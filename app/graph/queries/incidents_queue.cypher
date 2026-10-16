// The open-problems queue: each problem with its latest decision (not one that was replaced).
MATCH (i:Incident)
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision) WHERE d.status <> 'superseded'
       WITH d ORDER BY d.ts DESC LIMIT 1 RETURN d }
RETURN i.id AS id, i.status AS status, i.severity AS severity, i.opened_at AS opened_at, i.closed_at AS closed_at,
       d.id AS decision, d.kind AS kind, d.status AS decision_status, d.authority_level AS authority_level,
       d.suspect AS suspect, d.confidence_level AS confidence_level, d.signs_agree AS signs_agree,
       d.signs_total AS signs_total
ORDER BY i.opened_at DESC
LIMIT 100
