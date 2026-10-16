// Documents (procedures also get :SOP); the person who owns each one.
UNWIND $rows AS row
MERGE (d:Document {id: row.id})
SET d.kind = row.kind, d.title = row.title, d.reviewed_at = row.reviewed_at, d.source = $source
FOREACH (_ IN CASE WHEN row.kind = 'sop' THEN [1] ELSE [] END | SET d:SOP)
WITH d, row
OPTIONAL MATCH (p:Person) WHERE p.id = row.owner
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:OWNS]->(d))
RETURN count(d) AS n
