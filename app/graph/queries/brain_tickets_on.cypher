// Maintenance tickets on some assets, newest first.
MATCH (t:Ticket)-[:ON]->(a:Entity)
WHERE a.id IN $ids
RETURN t.id AS id, t.title AS title, t.status AS status, t.problem_code AS problem_code, t.opened_at AS opened_at,
       t.closed_at AS closed_at, a.id AS asset
ORDER BY opened_at DESC
LIMIT 10
