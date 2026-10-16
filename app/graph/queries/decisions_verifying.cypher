MATCH (x:Execution)-[:IMPLEMENTS]->(d:Decision {status: 'verifying'})
RETURN d.id AS decision, x.verifying_since AS since, x.verify_window_s AS window
