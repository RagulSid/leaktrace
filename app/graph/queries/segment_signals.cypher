// The evidence on one pipe section: leak alarms on it, pressure anomalies downstream through open
// links, leak alarms elsewhere in its zone, and its zones.
MATCH (p:Segment {id: $segment})
CALL { WITH p
  OPTIONAL MATCH (ld:Sensor {kind: 'leak', state: 'ALARM'})-[:MONITORS]->(p)
  RETURN collect(DISTINCT ld.id) AS leak_alarms }
CALL { WITH p
  OPTIONAL MATCH path = (p)-[:FLOWS_TO*1..8 {dir: 'normal'}]->(m)<-[:MONITORS]-(ps:Sensor {kind: 'pressure', state: 'ANOMALY'})
  WHERE all(r IN relationships(path) WHERE type(r) = 'MONITORS' OR r.cap_base > 0)
  RETURN collect(DISTINCT ps.id) AS pressure_anomalies }
CALL { WITH p
  OPTIONAL MATCH (p)-[:ROUTED_THROUGH]->(:Zone)<-[:IN_ZONE]-(l:Sensor {kind: 'leak', state: 'ALARM'})
  RETURN collect(DISTINCT l.id) AS zone_alarms }
CALL { WITH p
  OPTIONAL MATCH (p)-[:ROUTED_THROUGH]->(z:Zone)
  RETURN collect(DISTINCT z.id) AS zones }
RETURN p.id AS segment, leak_alarms, pressure_anomalies, zone_alarms, zones
