// Step 6: the check after the moves, and what was learned, for one problem.
MATCH (i:Incident {id: $incident})
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision)<-[:VERIFIES]-(v:Verification)
       RETURN collect({decision: d.id, passed: v.passed, failed: v.failed_checks}) AS checks }
CALL { WITH i OPTIONAL MATCH (e:Episode)-[:OF]->(i) RETURN count(e) AS steps_recorded }
CALL { MATCH (f:Fact {status: 'active'}) RETURN count(f) AS things_we_know }
CALL { MATCH (p:Playbook) RETURN count(p) AS proven_fixes }
RETURN i.status AS problem, checks, steps_recorded, things_we_know, proven_fixes
