// What a reporter may see about their report: no internal ids, only how far things have got.
MATCH (r:Report {code: $code})
CALL { WITH r OPTIONAL MATCH (r)-[:PART_OF]->(i:Incident) RETURN i }
CALL { WITH i OPTIONAL MATCH (o:Report)-[:PART_OF]->(i) RETURN count(o) AS reports }
CALL { WITH r RETURN size([(r)-[:ABOUT]->(a) | a]) AS linked }
CALL { WITH i OPTIONAL MATCH (i)-[:DECIDED]->(d:Decision) RETURN count(d) AS decisions,
       sum(CASE WHEN d.status IN ['executing', 'verifying'] THEN 1 ELSE 0 END) AS running }
CALL { WITH i OPTIONAL MATCH (w:WorkOrder {status: 'in_progress'})-[:FOR]->(i) RETURN count(w) AS crew_on_site }
RETURN r.code AS code, r.ts AS sent_at, i.status AS problem_status, i.closed_at AS closed_at, reports, linked,
       decisions, running, crew_on_site
