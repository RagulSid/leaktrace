// Writes per-edge properties from a parameter map; the property name never appears in query text.
UNWIND $rows AS row
MATCH ()-[r:FLOWS_TO {id: row.id}]->()
SET r += row.props
RETURN count(r) AS n
