MATCH (i:Incident {id: $incident})
UNWIND $options AS o
CREATE (op:Option {id: o.id, rank: o.rank, label: o.label, ops: o.ops, passed: o.passed,
                   failed_checks: o.failed_checks, checks_json: o.checks_json, disruption: o.disruption,
                   op_count: o.op_count, steps: o.steps, rollback: o.rollback, source: $source})
CREATE (i)-[:HAS_OPTION]->(op)
WITH op, o
UNWIND o.valves AS vid
MATCH (v:Valve {id: vid})
CREATE (op)-[:OPERATES]->(v)
RETURN count(*) AS n
