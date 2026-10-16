MATCH (i:Incident {id: $id})
CALL { WITH i OPTIONAL MATCH (i)-[:INVOLVED]->(n) RETURN collect(n.id) AS involved }
CALL { WITH i OPTIONAL MATCH (i)-[:INVOLVED]->(z:Zone) RETURN collect(z.id) AS zones }
CALL { WITH i OPTIONAL MATCH (r:Report)-[:PART_OF]->(i) RETURN collect(r.code) AS reports }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision) RETURN collect(d.id) AS decisions }
RETURN i.id AS id, i.status AS status, i.severity AS severity, i.opened_at AS opened_at,
       involved, zones, reports, decisions
