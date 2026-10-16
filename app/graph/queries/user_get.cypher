MATCH (u:User {id: $id})
RETURN u.id AS id, u.role AS role, u.pw_hash AS pw_hash, u.pw_salt AS pw_salt
