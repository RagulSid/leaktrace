// The active auto-mode policy that applies: a zone-specific one first, else one covering all zones.
MATCH (p:AuthorityPolicy {status: 'active'})
WHERE size(p.zones) = 0 OR $zone IN p.zones
RETURN properties(p) AS policy
ORDER BY size(p.zones) DESC, p.id
LIMIT 1
