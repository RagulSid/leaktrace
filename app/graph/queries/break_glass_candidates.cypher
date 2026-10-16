// Plans waiting for a person's OK that break-glass has not looked at yet.
MATCH (i:Incident {status: 'open'})-[:DECIDED]->(d:Decision {status: 'proposed', kind: 'act', authority_level: 'L3'})
WHERE coalesce(d.break_glass_checked, false) = false
RETURN d.id AS decision, d.ts AS ts, d.zone AS zone, i.id AS incident
