// A source names a thing on the map (or a ticket or document): resolved by exact id or name.
UNWIND $rows AS row
MATCH (s) WHERE (s:Document OR s:Ticket OR s:Message) AND s.id = row.source_id
MATCH (a) WHERE (a:Entity OR a:Ticket OR a:Document) AND a.id = row.target
MERGE (s)-[:MENTIONS]->(a)
RETURN count(a) AS n
