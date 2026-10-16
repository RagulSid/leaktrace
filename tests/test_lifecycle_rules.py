"""Pure rules behind execution: legal and illegal transitions, the graph fingerprint, verification checks,
the order valve moves are made in, and how a worker's report is read."""

import pytest

from app.actuation.adapter import FieldTaskActuator, make_before_break
from app.domain import fingerprint, lifecycle
from app.domain.confidence import Balance
from app.domain.verification import evaluate

LEGAL = [
    ("proposed", "approved"), ("proposed", "rejected"), ("proposed", "superseded"),
    ("approved", "proposed"), ("approved", "rejected"), ("approved", "superseded"), ("approved", "executing"),
    ("executing", "verifying"), ("executing", "failed"),
    ("verifying", "verified"), ("verifying", "failed"),
    ("failed", "rolling_back"), ("verified", "rolling_back"),
    ("rolling_back", "rolled_back"), ("rolling_back", "rollback_failed"),
]


@pytest.mark.parametrize("frm,to", LEGAL)
def test_legal_transitions(frm, to):
    lifecycle.check(frm, to)


def test_every_other_pair_is_illegal():
    states = sorted(lifecycle.STATES)
    illegal = [(a, b) for a in states for b in states if (a, b) not in set(LEGAL)]
    assert len(illegal) == len(states) ** 2 - len(LEGAL)
    for a, b in illegal:
        with pytest.raises(lifecycle.IllegalTransition):
            lifecycle.check(a, b)
    # the ones that matter most, spelled out
    for a, b in [("proposed", "executing"), ("proposed", "verified"), ("executing", "verified"),
                 ("verified", "executing"), ("rolled_back", "executing"), ("rejected", "approved"),
                 ("superseded", "approved"), ("recorded", "approved"), ("failed", "verified")]:
        assert not lifecycle.can(a, b)


def test_next_actions():
    assert lifecycle.next_actions("proposed", "L3") == ["approve", "reject"]
    assert lifecycle.next_actions("proposed", "L2") == ["execute"]
    assert lifecycle.next_actions("proposed", "L4") == []
    assert lifecycle.next_actions("failed", "L3") == ["rollback", "replan"]
    assert lifecycle.next_actions("executing", "L3") == []


SNAP = {
    "valves": [["V-01", "open", False, True], ["V-09", "closed", False, True]],
    "consumers": [["RACK-A1", 5, 20]], "workloads": [["WL-1", 5, False]],
    "edges": [["f04", 50, 50], ["f24", 0, 40]], "facts": [], "policies": [["POL", "active", 0.7, 3, 2, 4, 3]],
    "sensors": [["LS-A1", "ALARM"]], "meters": [["FM-A-IN", 47.0], ["FM-RA1", 20.1]],
}


def _with(**kw):
    return {**SNAP, **kw}


def test_fingerprint_ignores_order_and_meter_noise():
    shuffled = {k: list(reversed(v)) for k, v in SNAP.items()}
    assert fingerprint.fingerprint(shuffled) == fingerprint.fingerprint(SNAP)
    noisy = _with(meters=[["FM-A-IN", 48.9], ["FM-RA1", 19.0]])  # within max(2, 5%)
    assert fingerprint.material_changes(SNAP, noisy) == []


@pytest.mark.parametrize("change,expect", [
    (_with(valves=[["V-01", "closed", False, True], ["V-09", "closed", False, True]]), "valve V-01"),
    (_with(valves=[["V-01", "open", True, True], ["V-09", "closed", False, True]]), "valve V-01"),
    (_with(consumers=[["RACK-A1", 3, 20]]), "consumer RACK-A1"),
    (_with(facts=[["F-1", "stuck", "V-09"]]), "fact F-1"),
    (_with(sensors=[["LS-A1", "OK"]]), "sensor LS-A1"),
    (_with(edges=[["f04", 0, 50], ["f24", 0, 40]]), "edge f04"),
    (_with(meters=[["FM-A-IN", 55.0], ["FM-RA1", 20.1]]), "meter FM-A-IN"),
])
def test_material_changes(change, expect):
    out = fingerprint.material_changes(SNAP, change)
    assert out and out[0].startswith(expect), out
    assert fingerprint.fingerprint(change) != fingerprint.fingerprint(SNAP) or expect.startswith("meter")


EXPECTED = {"leak_segment": "SEG-A1", "isolation_meters": ["FM-A-IN"],
            "critical": {"RACK-A1": {"meters": ["FM-RA1"], "expected": 20.0}},
            "pressure_sensors": ["PS-MA"]}
BAL_OK = Balance("balanced", "FM-01", 50.0, 49.6, 0.4, ["FM-RA1"])


def _readings(**over):
    base = {"FM-A-IN": {"value": 0.3, "received_at": 10.0}, "FM-RA1": {"value": 19.8, "received_at": 10.0},
            "PS-MA": {"state": "OK", "received_at": 10.0}, "FM-01": {"value": 50.0, "received_at": 10.0}}
    for k, v in over.items():
        base[k] = {**base[k], **v}
    return base


def test_verification_passes_on_good_fresh_readings():
    checks, stale = evaluate(EXPECTED, _readings(), BAL_OK, since=5.0)
    assert stale == [] and all(c.passed for c in checks), [c for c in checks if not c.passed]
    assert [c.code for c in checks] == ["fresh_readings", "leak_isolated", "critical_supplied", "pressure_normal",
                                        "balance_restored"]


@pytest.mark.parametrize("over,balance,failed", [
    ({"FM-A-IN": {"value": 9.0}}, BAL_OK, ["leak_isolated"]),
    ({"FM-RA1": {"value": 0.0}}, BAL_OK, ["critical_supplied"]),
    ({"FM-RA1": {"value": 17.9}}, BAL_OK, ["critical_supplied"]),  # floor is 20 - max(2, 1.0) = 18
    ({"PS-MA": {"state": "ANOMALY"}}, BAL_OK, ["pressure_normal"]),
    ({}, Balance("imbalanced", "FM-01", 60.0, 49.0, 11.0, ["FM-RA1"]), ["balance_restored"]),
    ({}, Balance("unknown"), ["balance_restored"]),
    ({"FM-RA1": {"received_at": 4.0}}, BAL_OK, ["fresh_readings"]),
])
def test_each_verification_check_can_fail_alone(over, balance, failed):
    checks, stale = evaluate(EXPECTED, _readings(**over), balance, since=5.0)
    assert [c.code for c in checks if not c.passed] == failed
    assert (stale == ["FM-RA1"]) == (failed == ["fresh_readings"])


def test_without_isolation_meter_the_balance_decides():
    exp = {**EXPECTED, "isolation_meters": []}
    checks, _ = evaluate(exp, _readings(), Balance("imbalanced", "FM-01", 60.0, 40.0, 20.0, ["FM-RA1"]), since=5.0)
    iso = next(c for c in checks if c.code == "leak_isolated")
    assert not iso.passed and iso.detail["method"] == "balance"


def test_make_before_break_opens_first():
    assert make_before_break(["close:V-01", "close:V-07", "open:V-09"]) == [
        ("V-09", "open"), ("V-01", "closed"), ("V-07", "closed")]
    with pytest.raises(ValueError):
        make_before_break(["toggle:V-01"])


def test_commands_are_ordered_absolute_and_keyed():
    from app.actuation.adapter import Move

    cmds = FieldTaskActuator().commands("EXE-1", "forward", [Move("V-09", "open", "closed", ("f24",), (40,)),
                                                             Move("V-01", "closed", "open", ("f04",), (0,))])
    assert [(c["seq"], c["status"], c["target"]) for c in cmds] == [(1, "open", "open"), (2, "pending", "closed")]
    assert cmds[0]["idem_key"] == "EXE-1:forward:1:V-09:open" and len({c["idem_key"] for c in cmds}) == 2


def test_a_move_is_done_only_if_the_valve_was_seen_in_place():
    a = FieldTaskActuator()
    assert a.outcome("closed", "done", "closed", None) == ("done", None)
    assert a.outcome("closed", "done", "open", None) == ("failed", "wrong_state")
    assert a.outcome("open", "failed", "closed", "stuck") == ("failed", "stuck")
    assert a.outcome("open", "failed", None, None) == ("failed", "error")
