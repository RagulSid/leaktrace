// Sensors and meters named in a batch of readings, with their zone, what they watch or measure, and the
// state before this batch (a new problem opens only when a sensor goes into alarm, not while it stays there).
UNWIND $ids AS iid
MATCH (n:Entity {id: iid})
WHERE n:Sensor OR n:Meter
OPTIONAL MATCH (n)-[:IN_ZONE]->(z:Zone)
OPTIONAL MATCH (n)-[:MONITORS|MEASURES]->(a)
RETURN n.id AS id, CASE WHEN n:Sensor THEN 'sensor' ELSE 'meter' END AS instrument, n.kind AS kind,
       n.state AS prev_state, z.id AS zone, collect(a.id) AS watches
