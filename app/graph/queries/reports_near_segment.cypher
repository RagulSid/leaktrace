// Reports in this problem about the section, its zone, or anything located in that zone.
MATCH (p:Segment {id: $segment})-[:ROUTED_THROUGH]->(z:Zone)
MATCH (r:Report)-[:PART_OF]->(:Incident {id: $incident})
MATCH (r)-[:ABOUT]->(x)
WHERE x.id IN [p.id, z.id] OR (x)-[:LOCATED_IN|ROUTED_THROUGH]->(z)
RETURN count(DISTINCT r) AS reports, count(DISTINCT r.reporter) AS reporters, collect(DISTINCT r.id) AS report_ids
