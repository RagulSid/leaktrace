MATCH (i:Incident)
RETURN i.id AS id, i.status AS status, i.severity AS severity, i.opened_at AS opened_at
ORDER BY opened_at DESC
LIMIT 100
