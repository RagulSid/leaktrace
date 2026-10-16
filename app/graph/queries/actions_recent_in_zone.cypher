MATCH (a:Action {zone: $zone})
WHERE a.ts >= $since
RETURN count(a) AS n
