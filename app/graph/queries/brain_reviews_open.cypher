// Knowledge checks for a manager: names that matched nothing on the map.
MATCH (r:Review)-[:ABOUT]->(s)
WHERE r.kind = 'unresolved_mention' AND r.status = 'open'
RETURN r.id AS id, r.kind AS kind, r.reason AS reason, r.detail_json AS detail, r.created_at AS created_at,
       s.id AS source_id
ORDER BY id
