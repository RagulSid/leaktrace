// The practice data is complete (written at the very end of seeding): /health says "seeded" only after this.
MERGE (m:PracticeData {id: 'practice'})
SET m.ready_at = $ts, m.source = 'synthetic'
RETURN m.id AS id
