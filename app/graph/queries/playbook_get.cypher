MATCH (p:Playbook {key: $key})
RETURN properties(p) AS playbook
