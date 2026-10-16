// The most recent problem with a plan: its decision, suspected section, newest report and the key racks.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {kind: 'act'})
WITH i, d ORDER BY d.ts DESC LIMIT 1
CALL { WITH i OPTIONAL MATCH (r:Report)-[:PART_OF]->(i) WITH r ORDER BY r.ts DESC RETURN collect(r.code)[0] AS report }
RETURN i.id AS incident, d.id AS decision, d.suspect AS segment, report
