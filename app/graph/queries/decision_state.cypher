// Everything the execution engine needs about one decision: its status, the chosen plan, the active
// approval, the execution and the verifications.
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $id})
CALL { WITH d OPTIONAL MATCH (d)-[:CHOSE {role: 'chosen'}]->(o:Option)
       RETURN collect({id: o.id, ops: o.ops, label: o.label, rollback: o.rollback}) AS chosen }
CALL { WITH d OPTIONAL MATCH (ap:Approval {status: 'active'})-[:APPROVES]->(d) RETURN collect(properties(ap)) AS approvals }
CALL { WITH d OPTIONAL MATCH (x:Execution)-[:IMPLEMENTS]->(d) RETURN collect(properties(x)) AS executions }
CALL { WITH d OPTIONAL MATCH (vf:Verification)-[:VERIFIES]->(d) RETURN collect(properties(vf)) AS verifications }
RETURN properties(d) AS decision, i.id AS incident, chosen, approvals, executions, verifications
