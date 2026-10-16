MATCH (r:Review {id: $id})
WHERE r.status = 'open'
SET r.status = 'resolved', r.resolved_by = $by, r.resolved_at = $ts
RETURN r.id AS id
