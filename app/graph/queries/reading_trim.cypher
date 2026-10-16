// Keep only the newest $keep readings per instrument (capped history).
UNWIND $ids AS iid
MATCH (rd:Reading)-[:OF]->(:Entity {id: iid})
WITH iid, rd ORDER BY rd.ts DESC
WITH iid, collect(rd) AS rds
UNWIND rds[$keep..] AS old
DETACH DELETE old
RETURN count(*) AS deleted
