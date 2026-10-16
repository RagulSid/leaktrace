// Confirm or retire a fact. A fact a newer one replaced (superseded) stays as it is: confirming it would quietly
// bring back what the newer fact corrected.
MATCH (f:Fact {id: $id})
WHERE f.status <> 'superseded'
SET f.status = $status, f.last_confirmed_at = CASE WHEN $status = 'active' THEN $ts ELSE f.last_confirmed_at END,
    f.valid_to = CASE WHEN $status = 'retired' THEN $ts ELSE f.valid_to END, f.changed_by = $by
RETURN f.id AS id, f.status AS status
