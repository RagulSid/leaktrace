// Valves that are closed now: candidates to open as a backup link.
MATCH (v:Valve {state: 'closed'})
RETURN v.id AS id
ORDER BY id
