"""algo.maxFlow correctness on hand-calculated graphs, and gate G1 (capacity-variant what-if).

Hand calculations for the data-centre pack (see packs/datacenter/topology.json):
  - Base state: RACK-A1 can receive 25 (limited by its 25-unit feed).
  - Close V-01 only: Manifold A has no supply left, so RACK-A1 gets 0 (critical rack starved);
    the leak section SEG-A1 also gets 0.
  - Close V-01 and V-07, open backup link V-09: RACK-A1 gets 25 via row B and the backup link;
    SEG-A1 gets 0 (isolated).
  - Close V-01, open V-09, leave V-07 open: Manifold A back-feeds SEG-A1 through V-07, up to the
    backup link's 40, so the leak is not isolated.
"""

import pytest

from app.graph.algo import UnknownNodes, bfs_reach, max_flow
from app.graph.client import rows
from app.graph.whatif import apply_variant, clear_variant, variant, variant_property

DOCS_EXAMPLE = {
    "pack": "docs_example",
    "source": "synthetic",
    "nodes": [{"id": i, "labels": ["Junction"]} for i in ("A", "B", "C")],
    "flows": [
        {"id": "ab", "from": "A", "to": "B", "cap": 10},
        {"id": "ac", "from": "A", "to": "C", "cap": 5},
        {"id": "bc", "from": "B", "to": "C", "cap": 8},
    ],
}


def test_docs_hand_example_is_13(make_graph):
    tg = make_graph(DOCS_EXAMPLE)
    res = max_flow(tg, ["A"], ["C"])
    assert res.max_flow == 13
    assert res.edge_flows == {"ab": 8, "ac": 5, "bc": 8}


def test_maxflow_direction_and_errors(make_graph):
    tg = make_graph(DOCS_EXAMPLE)
    assert max_flow(tg, ["C"], ["A"]).max_flow == 0
    with pytest.raises(UnknownNodes):
        max_flow(tg, ["A"], ["NOPE"])
    with pytest.raises(ValueError):
        max_flow(tg, ["A"], ["A"])


def test_base_capacity_per_critical_rack(dc):
    assert max_flow(dc, ["CDU-1"], ["RACK-A1"]).max_flow == 25
    assert max_flow(dc, ["CDU-1"], ["RACK-B1"]).max_flow == 25
    # Both rows together are limited by the two 25-unit rack feeds per row: 4 racks x 25 = 100.
    assert max_flow(dc, ["CDU-1"], ["RACK-A1", "RACK-A2", "RACK-B1", "RACK-B2"]).max_flow == 100


def test_g1_nearest_valve_starves_critical_rack(dc):
    with variant(dc, "opt_close_v01", close_valves=["V-01"]) as cap:
        assert cap == "cap_opt_close_v01"
        assert max_flow(dc, ["CDU-1"], ["RACK-A1"], cap).max_flow == 0
        assert max_flow(dc, ["CDU-1"], ["SEG-A1"], cap).max_flow == 0
        assert max_flow(dc, ["CDU-1"], ["RACK-B1"], cap).max_flow == 25


def test_g1_backup_link_rescues_and_isolates(dc):
    with variant(dc, "opt_rescue", close_valves=["V-01", "V-07"], open_valves=["V-09"]) as cap:
        assert max_flow(dc, ["CDU-1"], ["SEG-A1"], cap).max_flow == 0
        assert max_flow(dc, ["CDU-1"], ["RACK-A1"], cap).max_flow == 25
        assert max_flow(dc, ["CDU-1"], ["RACK-B1"], cap).max_flow == 25
        # Both critical racks together: row B branch (50) carries both, 20 + 20 required.
        assert max_flow(dc, ["CDU-1"], ["RACK-A1", "RACK-B1"], cap).max_flow == 50


def test_g1_backfeed_defeats_isolation_without_downstream_valve(dc):
    with variant(dc, "opt_backfeed", close_valves=["V-01"], open_valves=["V-09"]) as cap:
        assert max_flow(dc, ["CDU-1"], ["SEG-A1"], cap).max_flow == 40


def test_g1_variants_coexist_and_clean_up(dc):
    a = apply_variant(dc, "opt_a", close_valves=["V-01"])
    b = apply_variant(dc, "opt_b", close_valves=["V-01", "V-07"], open_valves=["V-09"])
    assert max_flow(dc, ["CDU-1"], ["RACK-A1"], a).max_flow == 0
    assert max_flow(dc, ["CDU-1"], ["RACK-A1"], b).max_flow == 25
    assert max_flow(dc, ["CDU-1"], ["RACK-A1"]).max_flow == 25  # base untouched
    clear_variant(dc, "opt_a")
    clear_variant(dc, "opt_b")
    leftover = dc._g.ro_query(
        "MATCH ()-[r:FLOWS_TO]->() WHERE r.cap_opt_a IS NOT NULL OR r.cap_opt_b IS NOT NULL RETURN count(r)"
    ).result_set[0][0]
    assert leftover == 0
    with pytest.raises(Exception, match="missing attribute"):
        max_flow(dc, ["CDU-1"], ["RACK-A1"], a)  # FalkorDB refuses a capacity property that is gone


def test_g1_rejects_bad_ids_and_valves(dc):
    for bad in ["Opt", "opt-1", "x`y", "", "a" * 41, "cap base"]:
        with pytest.raises(ValueError):
            variant_property(bad)
    with pytest.raises(ValueError, match="control no"):
        apply_variant(dc, "opt_bad", close_valves=["V-99"])
    with pytest.raises(ValueError, match="both"):
        apply_variant(dc, "opt_bad", close_valves=["V-09"], open_valves=["V-09"])
    left = dc._g.ro_query("MATCH ()-[r:FLOWS_TO]->() WHERE r.cap_opt_bad IS NOT NULL RETURN count(r)").result_set[0][0]
    assert left == 0


def test_bfs_reach_follows_both_directions(dc):
    # algo.bfs takes one relationship type and no property filter, so it also walks backfeed edges.
    reach = set(bfs_reach(dc, "SEG-A1", 3))
    assert "CDU-1" not in reach  # f01 is one-way out of the cooling unit
    assert {"V-01", "V-07", "J-HDR", "J-MA"} <= reach
    downstream = {r["consumer"] for r in rows(dc.read("q2_trace_impact", {"segment": "SEG-A1"}))}
    assert downstream == {"RACK-A1", "RACK-A2"}
