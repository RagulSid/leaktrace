// Every node reachable over FLOWS_TO in either designed or backfeed direction (algo.bfs takes one type, no property filter).
MATCH (s:Entity {id: $start})
CALL algo.bfs(s, $depth, 'FLOWS_TO')
YIELD nodes
RETURN [n IN nodes | n.id] AS ids
