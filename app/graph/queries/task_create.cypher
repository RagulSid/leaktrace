UNWIND $ids AS id
CREATE (t:Task {id: id, kind: $kind, status: 'open', source: $source})
RETURN count(t) AS n
