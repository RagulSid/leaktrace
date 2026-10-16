// Step 4 (stored): every plan the Planner tested for this decision, with its result.
// Plan ids are o_<key>_<n>; every plan of one investigation shares the key of the chosen plan.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $decision})-[:CHOSE {role: 'chosen'}]->(c:Option)
MATCH (i)-[:HAS_OPTION]->(o:Option)
WHERE split(o.id, '_')[1] = split(c.id, '_')[1]
RETURN o.label AS plan, o.passed AS passes, o.failed_checks AS failed_checks, o.disruption AS disruption,
       o.id = c.id AS chosen
ORDER BY o.rank
