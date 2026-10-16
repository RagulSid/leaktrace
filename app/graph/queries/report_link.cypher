MATCH (r:Report {id: $report}), (i:Incident {id: $incident})
MERGE (r)-[:PART_OF]->(i)
WITH r
UNWIND $about AS aid
MATCH (n:Entity {id: aid})
MERGE (r)-[:ABOUT]->(n)
RETURN count(n) AS n
