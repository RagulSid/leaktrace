// Everything the incident report states, read from the graph.
MATCH (i:Incident {id: $id})
CALL { WITH i OPTIONAL MATCH (r:Report)-[:PART_OF]->(i) RETURN collect(r.code) AS reports }
CALL { WITH i OPTIONAL MATCH (i)-[:INVOLVED]->(z:Zone) RETURN collect(z.id) AS zones }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision)
       RETURN collect({id: d.id, kind: d.kind, summary: d.summary, authority_level: d.authority_level,
                       status: d.status, outcome: d.outcome, ts: d.ts}) AS decisions }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(:Decision)<-[:IMPLEMENTS]-(a:Action)
       RETURN collect({valve: a.valve, from_state: a.from_state, to_state: a.to_state, phase: a.phase, by: a.by,
                       ts: a.ts}) AS actions }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision)<-[:VERIFIES]-(v:Verification)
       RETURN collect({decision: d.id, passed: v.passed, failed_checks: v.failed_checks, ts: v.ts}) AS verifications }
CALL { WITH i OPTIONAL MATCH (w:WorkOrder)-[:FOR]->(i)
       RETURN collect({id: w.id, kind: w.kind, target: w.target, status: w.status, findings: w.findings}) AS work_orders }
CALL { WITH i OPTIONAL MATCH (t:Task)-[:FOR]->(i) WHERE t.kind IN $kinds
       OPTIONAL MATCH (t)-[:CLAIMED_BY]->(a:Agent)
       RETURN collect({kind: t.kind, status: t.status, agent: a.id, ts: t.created_at}) AS handoffs }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(:Decision)<-[:IMPLEMENTS]-(:Execution)<-[:PART_OF]-(:Task)<-[:EVIDENCED_BY]-(f:Fact)
       RETURN collect(DISTINCT {id: f.id, kind: f.kind, statement: f.statement}) AS from_moves }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(:Decision)<-[:VERIFIES]-(:Verification)<-[:EVIDENCED_BY]-(f:Fact)
       RETURN collect(DISTINCT {id: f.id, kind: f.kind, statement: f.statement}) AS from_checks }
CALL { WITH i OPTIONAL MATCH (w:WorkOrder)-[:FOR]->(i) OPTIONAL MATCH (f:Fact)-[:EVIDENCED_BY]->(w)
       RETURN collect(DISTINCT {id: f.id, kind: f.kind, statement: f.statement}) AS from_jobs }
RETURN i.id AS id, i.status AS status, i.severity AS severity, i.opened_at AS opened_at, i.closed_at AS closed_at,
       i.source AS source, reports, zones, decisions, actions, verifications, work_orders, handoffs,
       from_moves + from_checks + from_jobs AS facts
