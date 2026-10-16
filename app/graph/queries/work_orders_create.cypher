// Jobs for people from a decision: inspection, moving or informing about jobs on racks that lose flow,
// or agreeing a plan when no plan passes. Created once per decision.
// The count runs in a CALL: after a leading path MATCH, an aggregating WITH and UNWIND, the id lookup
// matches nothing on this FalkorDB build (regression test in tests/test_falkordb_quirks.py).
MATCH (i:Incident)-[:DECIDED]->(d:Decision {id: $decision})
CALL { WITH d OPTIONAL MATCH (old:WorkOrder)-[:DERIVED_FROM]->(d) RETURN count(old) AS existing }
WITH i, d, existing
WHERE existing = 0
UNWIND $orders AS o
MATCH (t:Entity) WHERE t.id = o.target
CREATE (w:WorkOrder {id: o.id, kind: o.kind, target: o.target, status: 'open', steps: o.steps, confirmed: [],
                     assigned_team: o.team, assigned_to: null, decision: d.id, created_at: $ts, created_by: $actor,
                     source: 'system'})
CREATE (w)-[:FOR]->(i), (w)-[:DERIVED_FROM]->(d), (w)-[:ON]->(t)
RETURN collect(w.id) AS ids
