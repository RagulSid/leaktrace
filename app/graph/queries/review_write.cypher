MATCH (d:Decision {id: $decision})
CREATE (r:Review {id: $id, kind: $kind, status: 'open', reason: $reason, detail_json: $detail, created_at: $ts,
                  source: 'system'})-[:ABOUT]->(d)
RETURN r.id AS id
