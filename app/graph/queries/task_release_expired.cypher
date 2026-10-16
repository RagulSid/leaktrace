// Leases that ran out go back to open so another worker can pick the step up.
MATCH (t:Task {status: 'claimed'})
WHERE t.lease_expires < $now
SET t.status = 'open', t.owner = null, t.released_at = $now
RETURN collect(t.id) AS ids
