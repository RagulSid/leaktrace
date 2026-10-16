MATCH (r:Review)-[:ABOUT]->(d:Decision)
RETURN r.id AS id, r.kind AS kind, r.status AS status, r.reason AS reason, r.created_at AS created_at,
       d.id AS decision
ORDER BY created_at DESC
