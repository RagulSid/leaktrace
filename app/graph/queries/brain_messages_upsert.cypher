// Shift-chat messages in their channel, with their author.
UNWIND $rows AS row
MERGE (c:Conversation {id: row.channel})
SET c.kind = 'shift_chat', c.source = $source
MERGE (m:Message {id: row.id})
SET m.role = 'chat', m.text = row.text, m.ts = row.ts, m.source = $source
MERGE (m)-[:IN]->(c)
WITH m, row
OPTIONAL MATCH (p:Person) WHERE p.id = row.author
FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END | MERGE (p)-[:AUTHORED]->(m))
RETURN count(m) AS n
