// "I see this too": a new report on the same problem and the same things, from a new reporter.
MATCH (r:Report {code: $code})-[:PART_OF]->(i:Incident)
WHERE i.status = 'open'
CREATE (n:Report {id: $id, code: $new_code, text: 'I see this too', reporter: $reporter, ts: $ts, hazard: false,
                  confirms: r.code, source: $source})-[:PART_OF]->(i)
WITH r, n
CALL { WITH r, n OPTIONAL MATCH (r)-[:ABOUT]->(a)
       FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | CREATE (n)-[:ABOUT]->(a))
       RETURN count(a) AS linked }
RETURN n.code AS code, linked
