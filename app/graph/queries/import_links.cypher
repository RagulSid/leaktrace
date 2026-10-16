// Template: {rel} is filled only from app.graph.schema.REL_TYPES.
UNWIND $rows AS row
MATCH (a:Entity {id: row.from}), (b:Entity {id: row.to})
MERGE (a)-[r:{rel}]->(b)
SET r += row.props, r.source = $source
RETURN count(r) AS n
