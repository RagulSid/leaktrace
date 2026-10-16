// Which of these ids exist on this customer's map (every citation is checked here), with what each one is.
UNWIND $ids AS x
MATCH (n) WHERE n.id = x
RETURN DISTINCT n.id AS id, labels(n) AS labels, coalesce(n.title, n.name, n.statement) AS title
