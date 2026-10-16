// Only a manager reaches this (checked in code); the property names come from a fixed list.
MATCH (p:AuthorityPolicy {id: $id})
SET p += $props, p.updated_at = $ts, p.updated_by = $by
CREATE (:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: 'policy', subject: p.id, actor: $by, role: $role,
                     from_status: $before, to_status: $after, reason: $reason, detail_json: $detail,
                     source: 'system'})-[:OF]->(p)
RETURN properties(p) AS policy
