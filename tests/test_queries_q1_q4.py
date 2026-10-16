"""Q1-Q4 on the small synthetic data-centre graph, checked against hand-worked answers."""

from app.graph.client import rows


def _set_sensor(tg, sensor_id, state):
    tg._g.query("MATCH (s:Sensor {id: $id}) SET s.state = $state", {"id": sensor_id, "state": state})


def test_q1_no_alarm_no_suspects(dc):
    assert rows(dc.read("q1_find_suspects")) == []


def test_q1_ranks_alarmed_section_with_downstream_anomaly_first(dc):
    _set_sensor(dc, "LS-A1", "ALARM")
    _set_sensor(dc, "PS-MA", "ANOMALY")
    _set_sensor(dc, "LS-B1", "ALARM")  # a second alarm with no pressure evidence
    got = [(r["segment"], r["direct_alarms"], r["downstream_anomalies"]) for r in rows(dc.read("q1_find_suspects"))]
    assert got == [
        ("SEG-A1", 1, 1),  # alarm on the section, pressure drop at Manifold A downstream
        ("SEG-B1", 1, 0),  # alarm on the section, no downstream anomaly
        ("SEG-A2", 0, 0),  # same zone, Manifold A is upstream of these, not downstream
        ("SEG-A3", 0, 0),
        ("SEG-B2", 0, 0),
        ("SEG-B3", 0, 0),
    ]


def test_q2_downstream_consumers_workloads_owners(dc):
    got = rows(dc.read("q2_trace_impact", {"segment": "SEG-A1"}))
    assert got == [
        {"consumer": "RACK-A1", "criticality": 5, "required_flow": 20, "workloads": ["WL-TRAIN-07"], "owners": ["T-ML"]},
        {"consumer": "RACK-A2", "criticality": 2, "required_flow": 15, "workloads": ["WL-BATCH-12"], "owners": ["T-DATA"]},
    ]


def test_q2_closed_backup_link_stops_the_trace(dc):
    assert {r["consumer"] for r in rows(dc.read("q2_trace_impact", {"segment": "SEG-B1"}))} == {"RACK-B1", "RACK-B2"}
    assert len(rows(dc.read("q2_trace_impact", {"segment": "SEG-01"}))) == 4


def test_q3_exposure_same_and_adjacent_zones(dc):
    got = [(r["zone"], r["consumer"], r["pdus"], r["energised"]) for r in rows(dc.read("q3_exposure", {"segment": "SEG-A1"}))]
    assert got == [("Z-A", "RACK-A1", ["PDU-A"], True), ("Z-A", "RACK-A2", ["PDU-A"], True)]
    # The supply main runs through the plant room, adjacent to both rows.
    assert len(rows(dc.read("q3_exposure", {"segment": "SEG-01"}))) == 4


def test_q4_recalls_past_incident_decision_and_active_facts(dc):
    dc._g.query(
        """
        MATCH (v:Valve {id:'V-09'}), (s:Segment {id:'SEG-A1'})
        CREATE (cur:Incident {id:'INC-2', source:'synthetic'}), (past:Incident {id:'INC-1', source:'synthetic'}),
               (d:Decision {id:'DEC-1', outcome:'failed', source:'synthetic'}),
               (f:Fact {id:'F-1', statement:'V-09 failed to open on cold start', status:'active', source:'synthetic'}),
               (old:Fact {id:'F-0', statement:'V-09 operates normally', status:'superseded', source:'synthetic'}),
               (cur)-[:INVOLVED]->(v), (cur)-[:INVOLVED]->(s), (past)-[:INVOLVED]->(v),
               (past)-[:DECIDED]->(d), (f)-[:ABOUT]->(v), (old)-[:ABOUT]->(v), (f)-[:SUPERSEDES]->(old)
        """
    )
    got = rows(dc.read("q4_recall_incidents", {"incident": "INC-2"}))
    assert got == [
        {"asset": "SEG-A1", "history": [], "facts": []},
        {"asset": "V-09", "history": [{"incident": "INC-1", "decision": "DEC-1", "outcome": "failed"}],
         "facts": ["V-09 failed to open on cold start"]},
    ]


def test_known_falkordb_quirk_optional_match_after_aggregation(make_graph):
    """Pins a FalkorDB behaviour our queries work around (graph module 60002): an OPTIONAL MATCH that
    filters its new node right after an aggregating WITH matches nothing, while the same match inside
    a CALL subquery works. If an upgrade fixes it, the first assertion fails and the workaround in
    q1_find_suspects / q4_recall_incidents can be simplified."""
    tg = make_graph()
    tg._g.query("CREATE (i:Incident {id:'I'})-[:INVOLVED]->(v:Valve {id:'V'}), (:Fact {status:'active', statement:'s'})-[:ABOUT]->(v)")
    plain = tg._g.query("MATCH (:Incident)-[:INVOLVED]->(a) WITH a, count(*) AS h "
                        "OPTIONAL MATCH (f:Fact {status:'active'})-[:ABOUT]->(a) RETURN collect(f.statement)").result_set
    sub = tg._g.query("MATCH (:Incident)-[:INVOLVED]->(a) WITH a, count(*) AS h "
                      "CALL { WITH a OPTIONAL MATCH (f:Fact {status:'active'})-[:ABOUT]->(a) RETURN collect(f.statement) AS s } "
                      "RETURN s").result_set
    assert plain == [[[]]]
    assert sub == [[["s"]]]
