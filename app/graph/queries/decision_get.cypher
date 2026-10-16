MATCH (d:Decision {id: $id})
CALL { WITH d OPTIONAL MATCH (d)-[c:CHOSE]->(o:Option) RETURN collect({role: c.role, option: o.id}) AS chosen }
CALL { WITH d OPTIONAL MATCH (i:Incident)-[:DECIDED]->(d) RETURN collect(i.id) AS incidents }
CALL { WITH d OPTIONAL MATCH (d)-[:JUSTIFIED_BY]->(e) RETURN collect(e.id) AS evidence }
RETURN properties(d) AS decision, chosen, incidents, evidence
