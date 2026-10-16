CALL db.meta.stats()
YIELD labels, relTypes, nodeCount, relCount
RETURN labels, relTypes, nodeCount, relCount
