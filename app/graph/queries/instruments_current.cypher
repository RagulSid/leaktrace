// Latest value or state of meters and sensors, with the server time the reading arrived.
UNWIND $ids AS iid
MATCH (n:Entity {id: iid})
RETURN n.id AS id, n.value AS value, n.state AS state, n.received_at AS received_at
