// Maximum flow from $sources to $targets (node ids) using the capacity property named by $cap.
// algo.maxFlow takes exactly one relationship type, so backfeed is modelled as FLOWS_TO {dir:'reverse'}.
MATCH (s:Entity) WHERE s.id IN $sources
WITH collect(s) AS ss
MATCH (t:Entity) WHERE t.id IN $targets
WITH ss, collect(t) AS ts
CALL algo.maxFlow({sourceNodes: ss, targetNodes: ts, relationshipTypes: ['FLOWS_TO'], capacityProperty: $cap})
YIELD edges, edgeFlows, maxFlow
RETURN maxFlow, size(ss) AS n_sources, size(ts) AS n_targets, [e IN edges | e.id] AS edge_ids, edgeFlows AS edge_flows
