// A name that looks like a map id but matches nothing: a manager checks it instead of it entering the map.
UNWIND $rows AS row
MATCH (s) WHERE (s:Document OR s:Ticket OR s:Message) AND s.id = row.source_id
MERGE (r:Review {id: row.id})
ON CREATE SET r.kind = 'unresolved_mention', r.status = 'open', r.reason = row.reason, r.detail_json = row.detail,
              r.created_at = $ts, r.source = $source
MERGE (r)-[:ABOUT]->(s)
RETURN count(r) AS n
