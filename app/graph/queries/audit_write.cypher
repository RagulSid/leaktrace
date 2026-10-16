MATCH (s) WHERE (s:Decision OR s:WorkOrder OR s:Incident) AND s.id = $subject
CREATE (a:AuditEvent {id: $audit, ts: $ts, seq: $seq, kind: $kind, subject: s.id, actor: $actor, role: $role,
                      from_status: $from, to_status: $to, reason: $reason, detail_json: $detail, source: 'system'})-[:OF]->(s)
RETURN a.id AS id
