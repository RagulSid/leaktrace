// Q1 Suspects: pipe sections in a zone with a leak alarm, ranked by direct leak alarms on the section
// and by pressure anomalies downstream of it (designed flow direction, open links only: cap_base > 0).
// CALL subqueries: in FalkorDB graph module 60002 (pinned image) an OPTIONAL MATCH that filters its new node right after an
// aggregating WITH matches nothing (filter is planned before the node is bound).
MATCH (l:Sensor {kind: 'leak', state: 'ALARM'})-[:IN_ZONE]->(z:Zone)<-[:ROUTED_THROUGH]-(p:Segment)
WITH p, z, count(DISTINCT l) AS zone_alarms
CALL {
  WITH p
  OPTIONAL MATCH (ld:Sensor {kind: 'leak', state: 'ALARM'})-[:MONITORS]->(p)
  RETURN count(DISTINCT ld) AS direct_alarms
}
CALL {
  WITH p
  OPTIONAL MATCH path = (p)-[:FLOWS_TO*1..8 {dir: 'normal'}]->(m)<-[:MONITORS]-(ps:Sensor {kind: 'pressure', state: 'ANOMALY'})
  WHERE all(r IN relationships(path) WHERE type(r) = 'MONITORS' OR r.cap_base > 0)
  RETURN count(DISTINCT ps) AS downstream_anomalies
}
RETURN p.id AS segment, z.id AS zone, direct_alarms, downstream_anomalies, zone_alarms
ORDER BY direct_alarms DESC, downstream_anomalies DESC, segment
