MATCH (w:WorkOrder)-[:FOR]->(i:Incident)
WHERE ($incident IS NULL OR i.id = $incident) AND ($kinds IS NULL OR w.kind IN $kinds)
RETURN w.id AS id, w.kind AS kind, w.target AS target, w.status AS status, w.steps AS steps,
       w.confirmed AS confirmed, w.assigned_team AS assigned_team, w.assigned_to AS assigned_to,
       w.decision AS decision, i.id AS incident, w.findings AS findings
ORDER BY w.created_at, id
