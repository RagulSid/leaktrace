// Step 1: a report, what it is about, and how many other reports are about the same things.
MATCH (r:Report {code: $code})-[:ABOUT]->(a)
CALL { WITH r, a OPTIONAL MATCH (a)<-[:ABOUT]-(other:Report) WHERE other.id <> r.id RETURN count(other) AS other_reports }
RETURN a.id AS thing, [l IN labels(a) WHERE l <> 'Entity'][0] AS kind, other_reports
ORDER BY other_reports DESC, thing
