// Active facts about assets, for the field crew and the timeline.
MATCH (f:Fact {status: 'active'})-[:ABOUT]->(a)
WHERE a.id IN $ids
RETURN f.id AS id, f.kind AS kind, a.id AS about, f.statement AS statement, f.source AS source
ORDER BY id
