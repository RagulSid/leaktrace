MATCH (z:Zone {id: $zone})
OPTIONAL MATCH (c:Consumer)-[:LOCATED_IN]->(z)
RETURN max(c.criticality) AS max_criticality
