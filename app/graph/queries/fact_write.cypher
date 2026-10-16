// A fact about an asset, linked to the node it rests on (a task, a work order or a verification).
MATCH (a:Entity) WHERE a.id = $about
MATCH (e) WHERE (e:Task OR e:WorkOrder OR e:Verification) AND e.id = $evidence
CREATE (f:Fact {id: $id, kind: $kind, status: 'active', statement: $statement, confidence: $confidence,
                valid_from: $ts, last_confirmed_at: $ts, source: $source})-[:ABOUT]->(a)
CREATE (f)-[:EVIDENCED_BY]->(e)
RETURN f.id AS id
