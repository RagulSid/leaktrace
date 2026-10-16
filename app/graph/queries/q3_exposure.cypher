// Q3 Exposure: consumers in the zone a pipe section runs through, or an adjacent zone, and their power feeds.
MATCH (p:Segment {id: $segment})-[:ROUTED_THROUGH]->(z:Zone)
MATCH (z)-[:ADJACENT_TO*0..1]-(z2:Zone)
MATCH (c:Consumer)-[:LOCATED_IN]->(z2)
OPTIONAL MATCH (c)-[:POWERED_BY]->(pdu:PDU)
RETURN z2.id AS zone, c.id AS consumer, c.criticality AS criticality,
       collect(DISTINCT pdu.id) AS pdus, max(CASE WHEN pdu.energised THEN 1 ELSE 0 END) = 1 AS energised
ORDER BY zone, consumer
