MATCH (:Incident {id: $incident})-[:HAS_OPTION]->(o:Option)
RETURN properties(o) AS option
ORDER BY o.rank
