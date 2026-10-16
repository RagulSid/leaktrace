// Decisions whose stored record names an asset (the record lists every plan and every check).
MATCH (i:Incident)-[:DECIDED]->(d:Decision)
WHERE d.explain_json CONTAINS $id
RETURN d.id AS id, d.kind AS kind, d.status AS status, d.ts AS ts, d.explain_json AS explain_json, i.id AS incident
ORDER BY ts DESC
LIMIT 10
