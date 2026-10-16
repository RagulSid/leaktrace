// Names and ids the report resolver matches free text against (resolution is always against the graph).
MATCH (n:Entity)
WHERE NOT n:AuthorityPolicy
RETURN n.id AS id, n.name AS name, labels(n) AS labels
