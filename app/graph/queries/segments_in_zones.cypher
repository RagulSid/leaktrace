// Fallback suspects when no leak alarm exists: every pipe section in the problem's zones.
MATCH (p:Segment)-[:ROUTED_THROUGH]->(z:Zone)
WHERE z.id IN $zones
RETURN p.id AS segment, z.id AS zone
ORDER BY segment
