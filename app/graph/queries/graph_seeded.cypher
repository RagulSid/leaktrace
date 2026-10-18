// How much a customer's graph holds: users who can sign in, things on the map, and whether the practice data was
// completed. Used by /health and to tell "graph empty" from "no problems".
CALL { MATCH (u:User) RETURN count(u) AS users }
CALL { MATCH (e:Entity) RETURN count(e) AS entities }
CALL { MATCH (m:PracticeData) RETURN count(m) AS ready }
RETURN users, entities, ready
