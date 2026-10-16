MATCH (t:Task {status: 'claimed'})
WHERE t.kind IN $kinds AND t.lease_expires < $now
SET t.status = 'open', t.owner = null, t.released_at = $now
RETURN collect(t.id) AS ids
