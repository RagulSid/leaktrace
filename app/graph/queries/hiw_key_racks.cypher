MATCH (c:Consumer) WHERE c.criticality >= $critical_min
RETURN collect(c.id) AS racks
