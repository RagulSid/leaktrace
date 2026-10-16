// When an approved decision is rejected or superseded, its approval stops being active.
MATCH (ap:Approval {status: 'active'})-[:APPROVES]->(d:Decision {id: $id})
SET ap.status = $status
RETURN count(ap) AS n
