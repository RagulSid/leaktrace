CALL db.relationshipTypes() YIELD relationshipType
RETURN collect(relationshipType) AS types
