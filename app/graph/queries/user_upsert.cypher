MERGE (u:User {id: $id})
SET u.role = $role, u.name = $name, u.pw_hash = $pw_hash, u.pw_salt = $pw_salt, u.source = $source
RETURN u.id AS id
