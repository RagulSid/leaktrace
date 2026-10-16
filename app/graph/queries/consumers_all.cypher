MATCH (c:Consumer)
RETURN c.id AS id, c.name AS name, c.criticality AS criticality, c.required_flow AS required_flow
ORDER BY id
