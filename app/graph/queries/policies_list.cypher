MATCH (p:AuthorityPolicy)
RETURN properties(p) AS policy
ORDER BY p.id
