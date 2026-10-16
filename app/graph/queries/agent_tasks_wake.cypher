// A step waiting on a decision opens again as soon as that decision's status changes.
MATCH (t:Task {status: 'waiting'})
MATCH (d:Decision) WHERE d.id = t.wait_decision AND d.status <> t.wait_seen_status
SET t.status = 'open', t.woken_at = $now, t.owner = null
RETURN collect(t.id) AS ids
