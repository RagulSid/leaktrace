// Flow balance for every metered region that contains the section: an inflow meter on the section or
// upstream of it, and every outflow meter downstream of that inflow through open links.
// unaccounted = inflow - sum(outflow) (no storage in the data-centre pack).
MATCH (mi:Meter)-[:MEASURES {direction: 'in'}]->(sin:Segment)
WHERE sin.id = $segment OR (sin)-[:FLOWS_TO*1..12 {dir: 'normal'}]->(:Segment {id: $segment})
CALL { WITH sin
  OPTIONAL MATCH path = (sin)-[:FLOWS_TO*1..12 {dir: 'normal'}]->(:Segment)<-[:MEASURES {direction: 'out'}]-(mo:Meter)
  WHERE all(r IN relationships(path) WHERE type(r) = 'MEASURES' OR r.cap_base > 0)
  RETURN collect(DISTINCT {id: mo.id, value: mo.value}) AS outs }
RETURN mi.id AS meter, sin.id AS segment, mi.value AS inflow, outs
ORDER BY size(outs), meter
