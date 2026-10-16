// Read-only execution status for the tool server: decision status, authority, steps and actions.
MATCH (d:Decision {id: $id})
CALL { WITH d OPTIONAL MATCH (x:Execution)-[:IMPLEMENTS]->(d)
       OPTIONAL MATCH (t:Task)-[:PART_OF]->(x)
       RETURN collect(CASE WHEN t IS NULL THEN NULL ELSE
                      {phase: t.phase, seq: t.seq, valve: t.valve, target: t.target, status: t.status} END) AS steps }
CALL { WITH d OPTIONAL MATCH (a:Action)-[:IMPLEMENTS]->(d) RETURN count(a) AS actions }
CALL { WITH d OPTIONAL MATCH (vf:Verification)-[:VERIFIES]->(d)
       RETURN collect(CASE WHEN vf IS NULL THEN NULL ELSE {passed: vf.passed, failed: vf.failed_checks} END) AS verifications }
RETURN d.id AS decision, d.status AS status, d.authority_level AS authority_level, d.outcome AS outcome,
       steps, actions, verifications
