// Active 'stuck' facts about an asset (from tickets or from the field crew).
MATCH (f:Fact)-[:ABOUT]->(a:Entity)
WHERE a.id = $asset AND f.status = 'active' AND f.kind = 'stuck'
RETURN f.id AS id
