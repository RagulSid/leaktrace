// Q2 What is affected: consumers downstream of a pipe section in the designed flow direction, through
// open links only (cap_base > 0, so a closed valve stops the trace), with workloads and owning teams.
MATCH path = (p:Segment {id: $segment})-[:FLOWS_TO*1..12 {dir: 'normal'}]->(c:Consumer)
WHERE all(r IN relationships(path) WHERE r.cap_base > 0)
WITH DISTINCT c
OPTIONAL MATCH (w:Workload)-[:RUNS_ON]->(c)
OPTIONAL MATCH (t:Team)-[:OWNS]->(w)
RETURN c.id AS consumer, c.criticality AS criticality, c.required_flow AS required_flow,
       collect(DISTINCT w.id) AS workloads, collect(DISTINCT t.id) AS owners
ORDER BY criticality DESC, consumer
