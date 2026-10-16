CREATE (i:Incident {id: $id, status: 'open', severity: $severity, opened_at: $ts, source: $source})
RETURN i.id AS id
