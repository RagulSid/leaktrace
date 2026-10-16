// A newer fact replaces older ones: they stay on the map (never deleted), marked superseded with valid_to.
MATCH (f:Fact) WHERE f.id = $fact
MATCH (old:Fact) WHERE old.id IN $old AND old.status = 'active'
SET old.status = 'superseded', old.valid_to = $ts, old.superseded_by = f.id
MERGE (f)-[:SUPERSEDES]->(old)
RETURN collect(old.id) AS ids
