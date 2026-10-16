CREATE (r:Report {id: $id, code: $code, text: $text, reporter: $reporter, ts: $ts, hazard: $hazard, source: $source})
RETURN r.id AS id
