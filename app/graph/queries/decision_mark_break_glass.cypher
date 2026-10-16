MATCH (d:Decision {id: $id})
SET d.break_glass_checked = true, d.break_glass_result = $result
RETURN d.id AS id
