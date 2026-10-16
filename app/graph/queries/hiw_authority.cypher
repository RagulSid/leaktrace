// Step 5: the checks behind "handled automatically" or "needs your OK", read from the decision and the policy.
MATCH (d:Decision {id: $decision})
CALL { MATCH (p:AuthorityPolicy {status: 'active'}) RETURN p ORDER BY p.id LIMIT 1 }
RETURN d.authority_level AS level, d.failed_conditions AS failed, d.confidence AS confidence,
       p.min_confidence AS min_confidence, p.max_auto_criticality AS max_auto_criticality,
       p.max_auto_operations AS max_auto_operations, p.frozen AS paused
