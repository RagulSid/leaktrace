// Ask LeakTrace corpus: teams (registry things, so they also carry :Entity like the pack's teams).
UNWIND $rows AS row
MERGE (t:Entity:Team {id: row.id})
SET t.name = row.name, t.source = $source
RETURN count(t) AS n
