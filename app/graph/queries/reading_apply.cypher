// received_at is the server's clock when the reading arrived: "fresh after the valve moves" is judged on
// it, not on the device's own timestamp.
UNWIND $rows AS row
MATCH (n:Entity {id: row.id})
SET n.state = coalesce(row.state, n.state), n.value = coalesce(row.value, n.value), n.reading_ts = row.ts,
    n.received_at = $received_at
CREATE (rd:Reading {id: row.rid, value: row.value, state: row.state, ts: row.ts, received_at: $received_at,
                    source: row.source})-[:OF]->(n)
RETURN count(rd) AS n
