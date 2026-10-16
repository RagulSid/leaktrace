// What the helpers did without a person's OK (auto mode or emergency action), newest first.
MATCH (a:Action)-[:AUTHORIZED_BY]->(:AuthorityPolicy)
MATCH (a)-[:IMPLEMENTS]->(d:Decision)<-[:DECIDED]-(i:Incident)
RETURN d.id AS decision, i.id AS incident, d.summary AS summary, d.status AS status, d.outcome AS outcome,
       collect({valve: a.valve, to_state: a.to_state, phase: a.phase, ts: a.ts}) AS actions, max(a.ts) AS last
ORDER BY last DESC
LIMIT 30
