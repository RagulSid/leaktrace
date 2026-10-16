// Dimension must match the embedding model (FalkorDB supports 1-4096). Score from queryNodes is a cosine distance: lower = closer.
CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) OPTIONS {dimension: $dim, similarityFunction: 'cosine'}
