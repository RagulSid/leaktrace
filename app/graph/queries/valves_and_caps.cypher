// Every valve state and every link capacity: used to show that an undo restored the exact prior state.
CALL { MATCH (v:Valve) RETURN collect([v.id, v.state]) AS valves }
CALL { MATCH ()-[r:FLOWS_TO]->() RETURN collect([r.id, r.cap_base]) AS edges }
RETURN valves, edges
