// Facts about some assets, or with some ids: what each rests on and what replaced what.
MATCH (f:Fact)-[:ABOUT]->(a:Entity)
WHERE a.id IN $about OR f.id IN $ids
CALL { WITH f OPTIONAL MATCH (f)-[:EVIDENCED_BY]->(e)
       RETURN collect({id: e.id, label: labels(e)[0], title: e.title}) AS evidence }
CALL { WITH f OPTIONAL MATCH (f)-[:SUPERSEDES]->(o:Fact) RETURN collect(o.id) AS replaces }
CALL { WITH f OPTIONAL MATCH (n:Fact)-[:SUPERSEDES]->(f) RETURN collect(n.id) AS replaced_by }
RETURN f.id AS id, f.kind AS kind, f.status AS status, f.statement AS statement, f.valid_from AS valid_from,
       f.valid_to AS valid_to, a.id AS about, a.name AS about_name, evidence, replaces, replaced_by
ORDER BY valid_from, id
