// Jobs, with their problem (a "find out" job asked from Ask LeakTrace may have none).
MATCH (w:WorkOrder)
CALL { WITH w OPTIONAL MATCH (w)-[:FOR]->(i:Incident) RETURN i.id AS incident }
WITH w, incident
WHERE ($incident IS NULL OR incident = $incident) AND ($kinds IS NULL OR w.kind IN $kinds)
CALL { WITH w OPTIONAL MATCH (w)-[:ON]->(t) RETURN t.name AS target_name }
RETURN w.id AS id, target_name, w.kind AS kind, w.target AS target, w.status AS status, w.steps AS steps,
       w.confirmed AS confirmed, w.assigned_team AS assigned_team, w.assigned_to AS assigned_to,
       w.decision AS decision, incident, w.findings AS findings, w.question AS question
ORDER BY w.created_at, id
