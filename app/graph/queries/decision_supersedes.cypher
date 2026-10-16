MATCH (n:Decision {id: $new}), (o:Decision {id: $old})
MERGE (n)-[:SUPERSEDES]->(o)
RETURN n.id AS id
