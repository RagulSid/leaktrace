// dir = 'normal' for the designed flow direction, 'reverse' for backfeed a two-way pipe allows.
// cap_base = capacity in the current state; open_cap = capacity when the controlling valve is open.
UNWIND $rows AS row
MATCH (a:Entity {id: row.from}), (b:Entity {id: row.to})
MERGE (a)-[r:FLOWS_TO {id: row.id}]->(b)
SET r.cap_base = row.cap_base, r.open_cap = row.open_cap, r.valve_id = row.valve_id, r.dir = row.dir, r.source = $source
RETURN count(r) AS n
