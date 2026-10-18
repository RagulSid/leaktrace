"""The startup step for a fresh container (ensure-demo): the demo customer is created only when its graph is empty,
with the practice story when a seed command is configured, and never with a made-up password."""

import pytest

from app import cli, config
from app.api.auth import login
from app.graph.client import TenantGraph, get_db, rows
from tests.conftest import DATACENTER_PACK, fresh_tenant

SHARED, MANAGER = "practice-only-password", "private-manager-password"


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    if TenantGraph(t).name in get_db().list_graphs():
        TenantGraph(t).delete()


def test_seeds_an_empty_graph_once(tenant):
    first = cli.ensure_demo(tenant, str(DATACENTER_PACK), password=SHARED, manager_password=MANAGER, seed_command="")
    assert first["seeded"] is True and first["story"] is False and first["nodes"] == 49 and "operator1" in first["users"]
    again = cli.ensure_demo(tenant, str(DATACENTER_PACK), password=SHARED, manager_password=MANAGER, seed_command="")
    assert again["seeded"] is False and again["nodes"] > 0
    assert login(tenant, "operator1", SHARED)["role"] == "operator"
    assert login(tenant, "manager1", MANAGER)["role"] == "manager"


def test_seed_command_tells_the_practice_story_and_leaves_existing_data_alone(tenant):
    out = cli.ensure_demo(tenant, str(DATACENTER_PACK), password=SHARED, manager_password=MANAGER)  # configured command
    assert out["seeded"] is True and out["story"] is True
    tg = TenantGraph(tenant)
    statuses = sorted(r["status"] for r in rows(tg.read("incidents_queue")))
    assert len(statuses) == 3  # handled automatically; closed by people (V-09 avoided); waiting for an OK
    assert login(tenant, "manager1", MANAGER) and login(tenant, "manager1", SHARED) is None
    before = rows(tg.read("stats"))[0]["nodeCount"]
    assert cli.ensure_demo(tenant, str(DATACENTER_PACK), password=SHARED, manager_password=MANAGER)["seeded"] is False
    assert rows(tg.read("stats"))[0]["nodeCount"] == before


def test_refuses_without_both_passwords(tenant, monkeypatch):
    monkeypatch.delenv("LEAKTRACE_DEMO_PASSWORD", raising=False)
    monkeypatch.delenv("LEAKTRACE_MANAGER_PASSWORD", raising=False)
    monkeypatch.setattr(config, "DEMO_PASSWORD", None)
    monkeypatch.setattr(config, "MANAGER_PASSWORD", None)
    with pytest.raises(cli.Refused):
        cli.ensure_demo(tenant, str(DATACENTER_PACK))
    with pytest.raises(cli.Refused) as e:
        cli.ensure_demo(tenant, str(DATACENTER_PACK), password=SHARED)  # the manager password is required too
    assert "LEAKTRACE_MANAGER_PASSWORD" in e.value.args[0]["hint"]
    assert TenantGraph(tenant).name not in get_db().list_graphs()  # nothing half-created
