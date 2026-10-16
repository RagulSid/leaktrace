// The first valves met walking out from a section along flow links in either direction: closing them
// is what isolation means.
MATCH path = (p:Segment {id: $segment})-[:FLOWS_TO*1..6]-(v:Valve)
WHERE none(n IN nodes(path)[1..-1] WHERE n:Valve)
RETURN DISTINCT v.id AS id
ORDER BY id
