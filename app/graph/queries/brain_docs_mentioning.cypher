// Documents that name some assets, with the passages of each that name it.
MATCH (d:Document)-[:MENTIONS]->(a:Entity)
WHERE a.id IN $ids
CALL { WITH d, a OPTIONAL MATCH (c:Chunk)-[:PART_OF]->(d) WHERE c.text CONTAINS a.id
       RETURN collect(c.text) AS passages }
RETURN d.id AS id, d.kind AS kind, d.title AS title, a.id AS about, passages
ORDER BY id
