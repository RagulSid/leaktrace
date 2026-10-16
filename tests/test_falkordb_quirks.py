"""Regression tests for FalkorDB behaviour our saved queries work around (graph module 60002).

If one of these starts failing, FalkorDB changed: re-check the workaround named in each test.
"""

import pytest
from redis.exceptions import ResponseError


@pytest.fixture
def g(make_graph):
    return make_graph()._g


def test_inline_property_from_an_earlier_match_matches_nothing(g):
    """`MATCH (a) MATCH (b {id: a.ref})` returns no rows (with an index on b's label it raises instead).
    Workaround in move_done / move_failed: `MATCH (b) WHERE b.id = a.ref`, or a WITH in between."""
    g.query("CREATE (:A {id: 'a', ref: 'b'}), (:Bx {id: 'b'})")
    assert g.query("MATCH (a:A) MATCH (b:Bx {id: a.ref}) RETURN b.id").result_set == []
    assert g.query("MATCH (a:A) MATCH (b:Bx) WHERE b.id = a.ref RETURN b.id").result_set == [["b"]]
    assert g.query("MATCH (a:A) WITH a MATCH (b:Bx {id: a.ref}) RETURN b.id").result_set == [["b"]]


QUIRK_SETUP = """CREATE (d:Decision {id:'D', status:'executing'}), (x:Execution {id:'X'})-[:IMPLEMENTS]->(d),
(t:Task {id:'T', kind:'valve_move', status:'claimed', owner:'w', idem_key:'k', valve:'V', target:'closed',
         edge_ids:['e1'], edge_caps:[0]})-[:PART_OF]->(x),
(:Valve {id:'V', state:'open'}), (:N {id:'a'})-[:FLOWS_TO {id:'e1', cap_base:5}]->(:N {id:'b'})"""

QUIRK_QUERY = """MATCH (t:Task {id: 'T'})-[:PART_OF]->(x:Execution)-[:IMPLEMENTS]->(d:Decision)
MATCH (v:Valve) WHERE v.id = t.valve
WITH t, x, d, v, v.state AS before
SET t.status = 'done', v.state = t.target
WITH t, x, d, v, before
CALL { WITH t
  UNWIND range(0, size(t.edge_ids) - 1) AS k
  MATCH ()-[r:FLOWS_TO {id: t.edge_ids[k]}]->()
  SET r.cap_base = t.edge_caps[k]
  RETURN count(r) AS edges }
RETURN edges"""


def test_write_call_after_projected_alias_and_set_fails(g):
    """A writing CALL {} after a projected alias plus a SET fails with "Variable r not found"; the same query
    without the alias works. Workaround in move_done: run the CALL first, project and SET after it.
    Nothing is applied when it fails (the query is atomic)."""
    g.query(QUIRK_SETUP)
    with pytest.raises(ResponseError, match="Variable r not found"):
        g.query(QUIRK_QUERY)
    assert g.query("MATCH (v:Valve) RETURN v.state").result_set == [["open"]]
    fixed = QUIRK_QUERY.replace("WITH t, x, d, v, v.state AS before", "WITH t, x, d, v").replace(
        "WITH t, x, d, v, before", "WITH t, x, d, v")
    assert g.query(fixed).result_set == [[1]]
    assert g.query("MATCH ()-[r:FLOWS_TO]->() RETURN r.cap_base").result_set == [[0]]


def test_a_failing_query_applies_none_of_its_writes(g):
    """Why each transition is one query: an error part-way undoes the writes made before it."""
    g.query("CREATE (:V {id: 'a', state: 'open'})")
    with pytest.raises(ResponseError):
        g.query("MATCH (v:V {id: 'a'}) SET v.state = 'closed' CREATE (:Marker) WITH v RETURN 1 / (size(v.id) - 1)")
    assert g.query("MATCH (v:V) RETURN v.state").result_set == [["open"]]
    assert g.query("MATCH (m:Marker) RETURN count(m)").result_set == [[0]]


def test_lookup_after_path_aggregation_and_unwind_matches_nothing(make_graph):
    """A query that starts with a path MATCH, then `OPTIONAL MATCH ... WITH ..., count(x)` and `UNWIND`, finds
    nothing with `MATCH (t:Entity) WHERE t.id = o.target`; starting from a single node it works.
    Workaround in work_orders_create: do the count inside a CALL subquery."""
    g = make_graph()._g
    g.query("CREATE (:Incident {id:'I'})-[:DECIDED]->(:Decision {id:'D'}), (:Entity {id:'Z'})")
    orders = {"orders": [{"target": "Z"}]}
    tail = "UNWIND $orders AS o MATCH (t:Entity) WHERE t.id = o.target RETURN t.id"
    from_path = ("MATCH (i:Incident)-[:DECIDED]->(d:Decision {id:'D'}) OPTIONAL MATCH (x:Nothing)-[:R]->(d) "
                 "WITH i, d, count(x) AS n WHERE n = 0 " + tail)
    from_node = ("MATCH (d:Decision {id:'D'}) OPTIONAL MATCH (x:Nothing)-[:R]->(d) WITH d, count(x) AS n WHERE n = 0 "
                 + tail)
    in_call = ("MATCH (i:Incident)-[:DECIDED]->(d:Decision {id:'D'}) CALL { WITH d OPTIONAL MATCH (x:Nothing)-[:R]->(d) "
               "RETURN count(x) AS n } WITH i, d, n WHERE n = 0 " + tail)
    assert g.ro_query(from_path, orders).result_set == []
    assert g.ro_query(from_node, orders).result_set == [["Z"]]
    assert g.ro_query(in_call, orders).result_set == [["Z"]]
