MATCH (s:Source)
RETURN collect(s.id) AS ids
