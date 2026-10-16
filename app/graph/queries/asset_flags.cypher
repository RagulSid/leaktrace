// Feasibility facts for assets a plan would operate: locked or irreversible in the registry, or an
// active memory fact saying it is stuck.
UNWIND $ids AS aid
MATCH (a:Entity {id: aid})
CALL { WITH a
  OPTIONAL MATCH (f:Fact {status: 'active'})-[:ABOUT]->(a)
  WHERE f.kind = 'stuck'
  RETURN collect(DISTINCT {fact: f.id, statement: f.statement}) AS stuck }
RETURN a.id AS id, a.state AS state, a.locked AS locked, a.reversible AS reversible, stuck
