// $nulls maps property names to null; setting a property to null removes it.
MATCH ()-[r:FLOWS_TO]->()
SET r += $nulls
RETURN count(r) AS n
