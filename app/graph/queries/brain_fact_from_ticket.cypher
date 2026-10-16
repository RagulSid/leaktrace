// The Record keeper's rule for tickets: a failed-to-operate ticket becomes a thing we know (a 'stuck' fact),
// a repair ticket a 'working' fact. Evidenced by the ticket; created once per ticket.
UNWIND $rows AS row
MATCH (t:Ticket) WHERE t.id = row.ticket
MATCH (a:Entity) WHERE a.id = row.asset
MERGE (f:Fact {id: row.fact})
ON CREATE SET f.kind = row.kind, f.status = 'active', f.statement = row.statement, f.confidence = row.confidence,
              f.valid_from = row.ts, f.last_confirmed_at = row.ts, f.source = $source
MERGE (f)-[:ABOUT]->(a)
MERGE (f)-[:EVIDENCED_BY]->(t)
RETURN f.id AS id
