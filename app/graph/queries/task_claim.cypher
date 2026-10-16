// Atomic claim: zero rows back means another worker won.
MATCH (t:Task {id: $id})
WHERE t.status = 'open'
SET t.status = 'claimed', t.owner = $agent, t.lease_expires = $until
RETURN t.id AS id
