UNWIND $rows AS row
MERGE (c:Chunk {id: row.id})
SET c.text = row.text, c.source = row.source, c.embedding = vecf32(row.embedding)
RETURN count(c) AS n
