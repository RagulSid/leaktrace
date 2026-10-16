MATCH (a:Agent)
RETURN a.id AS id, a.role AS role, a.status AS status, a.last_seen AS last_seen, a.chooser AS chooser, a.pid AS pid
ORDER BY id
