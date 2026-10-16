// Meaning search over passages (vector index); score is a cosine distance, lower is closer.
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vec))
YIELD node, score
MATCH (node)-[:PART_OF]->(s)
RETURN node.id AS chunk, node.text AS text, s.id AS source_id, labels(s) AS labels, s.title AS title, score
ORDER BY score
