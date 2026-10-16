MATCH (r:Report {code: $code})
OPTIONAL MATCH (r)-[:PART_OF]->(i:Incident)
RETURN r.code AS code, r.ts AS ts, i.id AS incident, i.status AS status
