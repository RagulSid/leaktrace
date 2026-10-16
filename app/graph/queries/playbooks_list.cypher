MATCH (p:Playbook)
RETURN p.id AS id, p.name AS name, p.segment AS segment, p.steps AS steps, p.success_count AS successes,
       p.failure_count AS failures, p.last_outcome AS last_outcome
ORDER BY p.success_count DESC, p.id
