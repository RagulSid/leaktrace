// What can confirm a plan worked: meters on the section and leak sensors watching it.
MATCH (p:Segment {id: $segment})
CALL { WITH p OPTIONAL MATCH (m:Meter)-[:MEASURES {direction: 'in'}]->(p) RETURN collect(m.id) AS isolation_meters }
CALL { WITH p OPTIONAL MATCH (s:Sensor {kind: 'leak'})-[:MONITORS]->(p) RETURN collect(s.id) AS isolation_sensors }
RETURN isolation_meters, isolation_sensors
