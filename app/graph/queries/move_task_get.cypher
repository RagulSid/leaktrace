MATCH (t:Task {id: $id, kind: 'valve_move'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)
RETURN properties(t) AS task, x.id AS execution, d.id AS decision, d.status AS decision_status
