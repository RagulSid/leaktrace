// Passages for meaning search: each one is part of its document, ticket or message and carries its vector.
UNWIND $rows AS row
MATCH (s) WHERE (s:Document OR s:Ticket OR s:Message) AND s.id = row.source_id
MERGE (c:Chunk {id: row.id})
SET c.text = row.text, c.source = $source, c.embedding = vecf32(row.embedding)
MERGE (c)-[:PART_OF]->(s)
RETURN count(c) AS n
