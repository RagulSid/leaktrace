CALL db.labels() YIELD label
RETURN collect(label) AS labels
