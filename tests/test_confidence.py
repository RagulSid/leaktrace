"""The confidence formula (app/domain/confidence.py) on hand cases."""

from app.domain.confidence import Balance, Signals, assess, balance_view, tolerance


def sig(**kw):
    base = dict(leak_alarms=[], zone_alarms=[], pressure_anomalies=[], reports=0, reporters=0, balance=Balance("unknown"))
    return Signals(**{**base, **kw})


def test_all_four_kinds():
    c = assess(sig(leak_alarms=["LS"], pressure_anomalies=["PS"], reports=2, reporters=2, balance=Balance("imbalanced")))
    assert c.score == 1.0 and c.level == "high" and c.signs_agree == 4


def test_single_kind_is_capped():
    assert assess(sig(leak_alarms=["LS"])).score == 0.35
    assert assess(sig(reports=3, reporters=3)).score == 0.2
    assert assess(sig(balance=Balance("imbalanced"))).score == 0.25
    assert assess(sig(leak_alarms=["LS"], zone_alarms=["LS", "LS2"])).score == 0.35  # still one kind


def test_contradiction_lowers_and_is_listed():
    c = assess(sig(leak_alarms=["LS"], reports=1, reporters=1, balance=Balance("balanced", meter="FM")))
    assert c.score == 0.15 and c.contradictions == ["flow balanced at FM"]


def test_missing_readings_are_neither_proof_nor_contradiction():
    c = assess(sig(leak_alarms=["LS"], pressure_anomalies=["PS"]))
    assert c.score == 0.55 and c.contradictions == []


def test_nearby_alarm_is_weaker():
    assert assess(sig(zone_alarms=["LS"], balance=Balance("imbalanced"))).score == 0.35


def test_balance_uses_smallest_complete_region():
    regions = [
        {"meter": "FM-01", "inflow": 83.0, "outs": [{"id": x, "value": v} for x, v in
                                                     [("A", 20.0), ("B", 15.0), ("C", 20.0), ("D", 15.0)]]},
        {"meter": "FM-A", "inflow": 47.0, "outs": [{"id": "A", "value": 20.0}, {"id": "B", "value": 15.0}]},
        {"meter": "FM-X", "inflow": 10.0, "outs": [{"id": "E", "value": None}]},  # incomplete: ignored
    ]
    b = balance_view(regions)
    assert (b.status, b.meter, b.unaccounted) == ("imbalanced", "FM-A", 12.0)
    assert balance_view([{"meter": "M", "inflow": 35.5, "outs": [{"id": "A", "value": 35.0}]}]).status == "balanced"
    assert balance_view([{"meter": "M", "inflow": None, "outs": []}]).status == "unknown"
    assert tolerance(10) == 2.0 and tolerance(100) == 5.0
