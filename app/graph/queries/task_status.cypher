MATCH (t:Task) WHERE t.id IN $ids
RETURN t.id AS id, t.status AS status, t.owner AS owner ORDER BY id
