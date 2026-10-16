// Template: {labels} is a ':'-joined list filled only from app.graph.schema.NODE_LABELS.
// Every imported topology or registry node also carries :Entity so cross-label lookups use one index.
UNWIND $rows AS row
MERGE (n:Entity:{labels} {id: row.id})
SET n += row.props, n.source = $source
RETURN count(n) AS n
