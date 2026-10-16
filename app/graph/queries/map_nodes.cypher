// The flow network as drawn on the map: pipe sections, valves, junctions, sources and racks.
MATCH (n:Entity)
WHERE n:Source OR n:Junction OR n:Segment OR n:Valve OR n:Consumer
RETURN n.id AS id, [l IN labels(n) WHERE l <> 'Entity'][0] AS kind, n.name AS name, n.state AS state,
       n.criticality AS criticality
ORDER BY id
