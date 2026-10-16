MATCH (f:Fact)-[:ABOUT]->(a)
RETURN f.id AS id, f.kind AS kind, f.status AS status, f.statement AS statement, f.confidence AS confidence,
       f.source AS source, f.valid_from AS valid_from, f.last_confirmed_at AS last_confirmed_at, a.id AS about
ORDER BY f.valid_from DESC
LIMIT 100
