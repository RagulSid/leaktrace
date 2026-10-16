// What a committed plan depends on, read in one go: valve states and locks, criticality and demand,
// workloads, link capacities, active facts, policy limits, sensor states and meter values.
// The stale-decision guard compares this snapshot at commit time with the one at execute time.
CALL { MATCH (v:Valve) RETURN collect([v.id, v.state, v.locked, v.reversible]) AS valves }
CALL { MATCH (c:Consumer) RETURN collect([c.id, c.criticality, c.required_flow]) AS consumers }
CALL { MATCH (w:Workload) RETURN collect([w.id, w.criticality, w.migratable]) AS workloads }
CALL { MATCH ()-[r:FLOWS_TO]->() RETURN collect([r.id, r.cap_base, r.open_cap]) AS edges }
CALL { MATCH (f:Fact {status: 'active'})-[:ABOUT]->(a) RETURN collect([f.id, f.kind, a.id]) AS facts }
CALL { MATCH (p:AuthorityPolicy)
       RETURN collect([p.id, p.status, p.min_confidence, p.max_auto_criticality, p.max_auto_operations,
                       p.critical_min_criticality, p.rate_limit_per_zone_per_hour]) AS policies }
CALL { MATCH (s:Sensor) RETURN collect([s.id, s.state]) AS sensors }
CALL { MATCH (m:Meter) RETURN collect([m.id, m.value]) AS meters }
RETURN valves, consumers, workloads, edges, facts, policies, sensors, meters
