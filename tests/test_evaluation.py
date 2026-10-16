"""Ablation and baselines (W7): the four approaches are scored by the simulated plant, and How it works shows the
saved result file, not numbers typed by hand."""

import json

from fastapi.testclient import TestClient

from app.api import how_it_works
from app.api.main import app
from scenario_generator import evaluate


def test_one_seed_scores_every_approach(tmp_path):
    out = tmp_path / "evaluation.json"
    assert evaluate.main(["--seeds", "1", "--out", str(out)]) == 0
    ev = json.loads(out.read_text(encoding="utf-8"))
    s = {(r["case"], r["approach"]): r for r in ev["summary"]}
    assert set(s) == {(c, a) for c in ("S1", "S5", "S3") for a in ("graph", "flat", "B1", "B2")}
    # what the plant measured on this map: the graph keeps the key racks running in S1 and asks a person
    assert s[("S1", "graph")]["leak_stopped"] == 1 and s[("S1", "graph")]["key_rack_short_runs"] == 0
    assert s[("S1", "graph")]["asked_person"] == 1 and s[("S1", "graph")]["max_flow_calls_avg"] > 0
    assert s[("S1", "flat")]["key_rack_short_runs"] == 1 and s[("S1", "B1")]["key_rack_short_runs"] == 1
    # no difference on the small leak, reported as such
    assert {k: v for k, v in s[("S5", "graph")].items() if k in ("leak_stopped", "racks_short_avg", "moves_avg")} == \
           {k: v for k, v in s[("S5", "flat")].items() if k in ("leak_stopped", "racks_short_avg", "moves_avg")}
    # the stuck backup link: the graph hands it to people instead of stopping the leak by starving a key rack
    assert s[("S3", "graph")]["leak_stopped"] == 0 and s[("S3", "graph")]["key_rack_short_runs"] == 0
    assert ev["not_run"] and all(r["errors"] == 0 for r in ev["summary"])


def test_how_it_works_reads_the_saved_file(tmp_path, monkeypatch):
    f = tmp_path / "evaluation.json"
    monkeypatch.setattr(how_it_works, "EVALUATION_FILE", f)
    c = TestClient(app)
    assert c.get("/how-it-works/proof").json()["evaluation"] is None  # nothing saved: "Not measured yet"
    f.write_text(json.dumps({"summary": [{"case": "S1", "approach": "graph", "runs": 7}]}), encoding="utf-8")
    assert c.get("/how-it-works/proof").json()["evaluation"]["summary"][0]["runs"] == 7
