// score is cosine distance (0 = same direction); smaller is more similar.
CALL db.idx.vector.queryNodes('Chunk', 'embedding', $k, vecf32($vec))
YIELD node, score
RETURN node.id AS id, node.text AS text, score
ORDER BY score
