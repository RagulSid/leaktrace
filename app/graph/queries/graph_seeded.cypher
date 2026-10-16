// How much a customer's graph holds: users who can sign in, and things on the map. Used by /health and to tell
// "graph empty" from "no problems".
CALL { MATCH (u:User) RETURN count(u) AS users }
CALL { MATCH (e:Entity) RETURN count(e) AS entities }
RETURN users, entities
