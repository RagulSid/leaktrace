MATCH (a)-[r:FLOWS_TO {dir: 'normal'}]->(b)
RETURN r.id AS id, a.id AS source, b.id AS target, r.cap_base AS cap_base, r.open_cap AS open_cap
ORDER BY id
