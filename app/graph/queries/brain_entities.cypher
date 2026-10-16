// Every thing on the map with its name, to resolve names and ids in a question or a text.
MATCH (n:Entity)
RETURN n.id AS id, n.name AS name, labels(n) AS labels
