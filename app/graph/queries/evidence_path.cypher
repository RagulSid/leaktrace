// Shortest designed-direction path through open links from a section to one consumer (for the map).
MATCH path = (p:Segment {id: $segment})-[:FLOWS_TO*1..12 {dir: 'normal'}]->(c:Consumer {id: $consumer})
WHERE all(r IN relationships(path) WHERE r.cap_base > 0)
RETURN [n IN nodes(path) | n.id] AS ids
ORDER BY size(ids)
LIMIT 1
