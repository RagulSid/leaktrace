// Sensors and meters named in a batch of readings, with their zone and what they watch or measure.
UNWIND $ids AS iid
MATCH (n:Entity {id: iid})
WHERE n:Sensor OR n:Meter
OPTIONAL MATCH (n)-[:IN_ZONE]->(z:Zone)
OPTIONAL MATCH (n)-[:MONITORS|MEASURES]->(a)
RETURN n.id AS id, CASE WHEN n:Sensor THEN 'sensor' ELSE 'meter' END AS instrument, n.kind AS kind,
       z.id AS zone, collect(a.id) AS watches
