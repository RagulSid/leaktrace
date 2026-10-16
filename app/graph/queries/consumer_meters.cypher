// Outflow meters on the pipe that feeds each consumer.
UNWIND $ids AS cid
MATCH (c:Consumer {id: cid})
OPTIONAL MATCH (m:Meter)-[:MEASURES {direction: 'out'}]->(:Segment)-[:FLOWS_TO {dir: 'normal'}]->(c)
RETURN c.id AS consumer, collect(m.id) AS meters
