"""Task leases: an expired claim goes back to open and can be picked up by someone else."""

from app.agents import tasks


def _incident(tg):
    tg.write("incident_create", {"id": "INC-T1", "severity": "low", "ts": 0.0, "source": "synthetic"})
    return "INC-T1"


def test_expired_lease_returns_to_open(make_graph):
    tg = make_graph()
    inc = _incident(tg)
    a = tasks.create(tg, incident=inc, kind="inspect", payload={}, actor="test", source="synthetic")
    b = tasks.create(tg, incident=inc, kind="inspect", payload={}, actor="test", source="synthetic")
    now = 1000.0
    assert tasks.claim(tg, a, "worker_1", lease_s=10, now=now)
    assert tasks.claim(tg, b, "worker_1", lease_s=100, now=now)
    assert not tasks.claim(tg, a, "worker_2", lease_s=10, now=now)  # still held

    assert tasks.release_expired(tg, now=now + 5) == []  # nothing expired yet
    assert tasks.release_expired(tg, now=now + 11) == [a]  # only a's lease ran out
    st = {s["id"]: s for s in tasks.status(tg, [a, b])}
    assert st[a]["status"] == "open" and st[a]["owner"] is None
    assert st[b]["status"] == "claimed" and st[b]["owner"] == "worker_1"

    assert tasks.claim(tg, a, "worker_2", lease_s=10, now=now + 12)
    assert {s["id"]: s["owner"] for s in tasks.status(tg, [a])} == {a: "worker_2"}


def test_task_is_linked_to_its_incident(make_graph):
    tg = make_graph()
    inc = _incident(tg)
    t = tasks.create(tg, incident=inc, kind="inspect", payload={"zones": ["Z-A"]}, actor="test", source="synthetic")
    linked = tg._g.ro_query("MATCH (:Task {id: $t})-[:FOR]->(i:Incident) RETURN i.id", {"t": t}).result_set
    assert linked == [[inc]]
