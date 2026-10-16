// The shape of the map: how many links of each kind join each kind of thing.
MATCH (a)-[r]->(b)
WITH [l IN labels(a) WHERE l <> 'Entity'][0] AS from_kind, type(r) AS link, [l IN labels(b) WHERE l <> 'Entity'][0] AS to_kind
RETURN from_kind, link, to_kind, count(*) AS links
ORDER BY links DESC
LIMIT 40
