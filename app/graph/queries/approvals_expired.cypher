MATCH (ap:Approval {status: 'active'})-[:APPROVES]->(d:Decision {status: 'approved'})
WHERE ap.expires_at < $now
RETURN d.id AS decision, ap.id AS approval
