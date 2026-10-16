// Who owns what: a team owns an asset on the map (from the ownership chart).
UNWIND $rows AS row
MATCH (t:Team) WHERE t.id = row.team
MATCH (a:Entity) WHERE a.id = row.asset
MERGE (t)-[:OWNS]->(a)
RETURN count(a) AS n
